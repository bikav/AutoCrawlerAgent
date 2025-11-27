# AutoCrawlerAgent

> 面向 `LangChain/auto-crawler-agent/main.py` 的使用文档。
> 
> 该脚本会根据设定的关键词，使用 Tavily 搜索近三个月内的相关网页，并将结果导出为 PDF。
> 
> 对于“直接是 PDF 的链接”会优先采用二进制下载保存，无法直接下载时回退为用 Playwright 将 HTML 页面打印为 PDF。

## 前置准备
- Python ≥ 3.11

### Tavily 密钥获取：
- 访问 [Tavily 官网](https://www.tavily.com/) 注册账号。
- 登录后，在 [API Keys 页面](https://app.tavily.com/home) 获取 `TAVILY_API_KEY`。
- 在 `.env` 中配置 Tavily API Key：
  - `TAVILY_API_KEY=你的密钥`

### 安装依赖：
- `pip install -r requirements.txt`

## 快速开始
### 运行脚本：
- `python ./auto-crawler-agent/main.py`

### 默认输出目录：
- `knowledge_base`

### 切换输出目录：
- 在文件末尾将 `main()` 中的 output_dir 改为 `目录名称`

## 功能与流程
### 多关键词组合查询，提高覆盖面：
- `generate_queries()`

### 在近三个月日期范围内搜索：
- `search_urls(queries, months=3, max_results_per_query=50)`

### 本地持久化：
- 将已导出 URL 保存至 `output_dir/exported_urls.txt`，下次运行只处理未导出链接。

### 导出 PDF：
`build_pdf_content(urls, output_dir, start_index)`：

- 链接直接指向 PDF 文件：使用 `httpx` 下载保存到 `output_dir`，文件名取 `Content-Disposition` 或 URL 路径。
- 链接触发浏览器下载：使用 Playwright 的下载钩子保存到 `output_dir`。
- 普通网页：用 Playwright 将页面打印成 `output_dir/{file_prefix}_{index}.pdf`。
- 文件名冲突时自动添加后缀 `_1`, `_2`，避免覆盖。
- `index` 从已导出数量+1开始，避免编号重复。

## 参数说明
### 关键词配置：
- 在 `generate_queries()` 中修改或扩展关键字组合。

### 搜索参数设置：
`search_urls(queries: List[str], months: int = 3, max_results_per_query: int = 50)`
  - `months`：搜索时间范围（月数），默认 3。
  - `max_results_per_query`：每组关键词最大返回条数，默认 50。

## 常见问题
- “未搜索到CBTI相关资源”
  - 请检查网络或 `.env` 中是否配置了 `TAVILY_API_KEY`。
- 直接 PDF 链接 `Page.goto` 报错（如 `net::ERR_HTTP2_PROTOCOL_ERROR`）
  - 脚本已改为优先用 `httpx` 直接下载 PDF；若站点需要额外请求头或登录，可在后续定制。
- 导出时提示 “Download is starting”
  - 对这类链接使用了 Playwright 的下载钩子捕获并保存。
- Playwright 报 “浏览器未安装/版本不匹配”
  - 运行 `playwright install chromium` 安装对应内核。

## 目录与输出
默认输出目录：`knowledge_base/`

- PDF 文件：
  - 直接下载的 PDF：原始文件名（若冲突自动加后缀）。
  - HTML 打印的 PDF：`{file_prefix}_{index}.pdf`。
- 已导出 URL 记录：`exported_urls.txt`

