import os
import re
import asyncio
import httpx
from typing import List, Set
from dotenv import load_dotenv
from urllib.parse import urlparse
from datetime import datetime, timedelta

from langchain_tavily import TavilySearch
from playwright.async_api import async_playwright

load_dotenv(override=True)
EXPORTED_URLS_FILE = os.path.abspath("knowledge_base/exported_urls.txt")


def generate_queries() -> List[str]:
    """构造多组关键词组合以扩大覆盖面"""
    return [
        "失眠 认知行为疗法",
        "CBT-I",
        "Cognitive Behavioral Therapy for Insomnia",
    ]


def search_urls(queries: List[str], months: int = 3, max_results_per_query: int = 50) -> List[str]:
    """
    使用 Tavily 获取近三个月内的相关资源 URL 列表。
    兼容不同返回结构，自动去重。
    """

    search_tool = TavilySearch(
        max_results=max_results_per_query,
        search_depth="advanced",
        topic="general",
    )

    end_date = datetime.utcnow().date()
    start_date = (end_date - timedelta(days=months * 30))

    seen = set()
    merged_urls: List[str] = []

    for q in queries:
        try:
            resp = search_tool.invoke({
                "query": q,
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
            })
        except Exception as e:
            print(f"搜索失败：{q}，错误：{e}")
            continue

        # 兼容字典/列表/字符串返回
        urls: List[str] = []
        if isinstance(resp, dict):
            for item in resp.get("results", []):
                url = item.get("url")
                if url:
                    urls.append(url)
        elif isinstance(resp, list):
            for item in resp:
                if isinstance(item, dict):
                    url = item.get("url")
                    if url:
                        urls.append(url)
                elif isinstance(item, str) and item.startswith("http"):
                    urls.append(item)
        else:
            urls += re.findall(r"https?://[^\s)]+", str(resp))

        for u in urls:
            if u and u not in seen:
                seen.add(u)
                merged_urls.append(u)

    return merged_urls


def read_exported_urls(file_path: str) -> Set[str]:
    """获取已导出的 URL 列表"""
    if not os.path.exists(file_path):
        return set()
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return {line.strip() for line in f if line.strip()}
    except Exception:
        return set()


def save_exported_urls(file_path: str, urls: List[str]) -> None:
    """将新导出的 URL 列表追加到文件中，自动去重"""
    existing = read_exported_urls(file_path)
    combined = existing.union({u.strip() for u in urls if u})
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        for u in sorted(combined):  # 对所有 URL 按字母顺序排序
            f.write(u + "\n")


def ensure_unique_path(dir_path: str, filename: str) -> str:
    """确保文件路径唯一，避免覆盖已存在文件"""
    base, ext = os.path.splitext(filename)
    candidate = os.path.join(dir_path, filename)
    i = 1
    while os.path.exists(candidate):
        candidate = os.path.join(dir_path, f"{base}_{i}{ext}")
        i += 1
    return os.path.abspath(candidate)


def filename_from_headers_or_url(url: str, headers: dict) -> str:
    """根据响应头或URL生成唯一的PDF文件名"""
    cd = headers.get("content-disposition", "") if headers else ""
    m = re.search(r'filename\*?=\s*"?([^";]+)"?', cd, re.I)
    name = m.group(1) if m else os.path.basename(urlparse(url).path)
    if not name:
        name = "download.pdf"
    if not name.lower().endswith(".pdf"):
        name += ".pdf"
    return name


async def download_pdf_direct(client: httpx.AsyncClient, url: str, dest_dir: str) -> str | None:
    """直接下载PDF文件，返回保存路径或None"""
    try:
        resp = await client.get(
            url,
            timeout=20.0,
            follow_redirects=True,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Accept": "application/pdf,application/octet-stream,*/*",
            },
        )
        ct = (resp.headers.get("content-type") or "").lower()  # Content-Type 告知是 HTML 还是 PDF
        cd = (resp.headers.get("content-disposition") or "").lower()  # Content-Disposition 告知是否“附件下载”（常见于强制下载）
        is_pdf = url.lower().split("?")[0].endswith(".pdf") or ("application/pdf" in ct) or ("filename" in cd and ".pdf" in cd)  # 判断链接是否真的指向PDF文件
        if not is_pdf:
            return None

        fname = filename_from_headers_or_url(url, resp.headers)  # 提取文件名字
        os.makedirs(dest_dir, exist_ok=True)
        path = ensure_unique_path(dest_dir, fname)
        with open(path, "wb") as f:
            f.write(resp.content)
        return path
    except Exception as e:
        print(f"直接下载PDF失败：{url}，错误：{e}")
        return None


async def build_pdf_content(output_dir: str, file_prefix: str, urls: List[str], start_index: int = 1) -> List[str]:
    """使用 Playwright 异步 API 将每个 URL 导出为独立 PDF，返回文件路径列表。对直接PDF链接进行二进制下载保存。"""
    pdf_paths: List[str] = []
    async with async_playwright() as p:
        browser = await p.chromium.launch()  # 启动 Chromium 浏览器
        context = await browser.new_context(locale="zh-CN", accept_downloads=True)  # 创建无痕窗口，允许浏览器接收下载
        os.makedirs(output_dir, exist_ok=True)
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            for idx, url in enumerate(urls, start_index):
                page = None
                try:
                    # 1) 优先尝试直接下载PDF
                    direct_path = await download_pdf_direct(client, url, output_dir)
                    if direct_path:
                        pdf_paths.append(direct_path)
                        continue

                    # 2) 尝试导航自动触发下载事件（某些链接会自动开始下载）
                    page = await context.new_page()
                    try:
                        async with page.expect_download() as d_info:
                            await page.goto(url)
                        download = await d_info.value
                        suggested = download.suggested_filename or os.path.basename(urlparse(url).path) or f"{file_prefix}_{idx}.pdf"
                        if not suggested.lower().endswith(".pdf"):
                            suggested = f"{file_prefix}_{idx}.pdf"
                        pdf_path = ensure_unique_path(output_dir, suggested)
                        await download.save_as(pdf_path)
                        pdf_paths.append(pdf_path)
                        continue
                    except Exception:
                        # 未触发下载则回退为打印成PDF
                        pass

                    # 3) 回退：将HTML打印成PDF
                    try:
                        await page.goto(url, wait_until="load")
                    except Exception:
                        pass
                    try:
                        await page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:
                        pass
                    try:
                        await page.emulate_media(media="print")
                    except Exception:
                        pass

                    pdf_path = os.path.abspath(f"{output_dir}/{file_prefix}_{idx}.pdf")
                    await page.pdf(
                        path=pdf_path,
                        format="A4",
                        print_background=True,
                    )
                    pdf_paths.append(pdf_path)
                except Exception as e:
                    print(f"导出失败：{url}，错误：{e}")
                finally:
                    try:
                        if page:
                            await page.close()
                    except Exception:
                        pass
        try:
            await context.close()
        finally:
            try:
                await browser.close()
            except Exception:
                pass
    return pdf_paths


def main():
    # 1. 搜索相关资源
    queries = generate_queries()
    urls = search_urls(queries=queries, months=3, max_results_per_query=5)
    if not urls:
        print("未搜索到相关资源，请检查网络或 Tavily API 配置。")
        return

    exported_urls = read_exported_urls(EXPORTED_URLS_FILE)
    new_urls = [u for u in urls if u not in exported_urls]

    print(f"命中链接数量：{len(urls)}，其中未导出链接：{len(new_urls)}")
    if not new_urls:
        print("没有新的 URL 需要导出。")
        return

    print("将处理以下未导出链接：")
    for u in new_urls:
        print("- ", u)

    # 2. 异步导出每个网页为独立 PDF
    output_dir = "knowledge_base"
    file_prefix = "resource"
    start_index = len(exported_urls) + 1
    pdf_paths = asyncio.run(build_pdf_content(output_dir, file_prefix, new_urls, start_index=start_index))

    # 3. 保存已导出的 URL ，并输出导出结果
    save_exported_urls(EXPORTED_URLS_FILE, new_urls)
    print("导出PDF完成：")
    for p in pdf_paths:
        print("- ", p)


if __name__ == "__main__":
    main()
