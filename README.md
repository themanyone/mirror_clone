# Mirror Clone

A robust, production-ready web page mirror utility that downloads HTML pages and all their linked resources to a local directory.

## 🚀 Features

- **Recursive Download**: Follows links to download resources up to a configurable depth
- **Connection Pooling**: Efficient HTTP connections via `requests.Session`
- **Retry Logic**: Automatic retries for transient failures (500-504, 429)
- **Depth Control**: Prevents runaway downloads with configurable recursion limit
- **Referer Support**: Bypass origin-checking servers with custom referer headers
- **file:// Support**: Handles local file paths alongside HTTP/HTTPS URLs
- **Graceful Error Handling**: Specific handlers for timeouts, connection errors, and HTTP failures
- **Duplicate Prevention**: Tracks processed URLs to avoid redundant downloads

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/your-username/mirror-clone.git
cd mirror-clone

# Make executable
chmod +x mirror_page.py

# Run
./mirror_page.py https://example.com ./output -d 2 -r "https://example.com"
```

## 🛠️ Usage

```bash
# Basic usage
python mirror_page.py https://example.com ./mirror

# With referer header (bypasses origin checks)
python mirror_page.py https://example.com ./mirror -r "https://example.com"

# Recursive download up to depth 3
python mirror_page.py https://example.com ./mirror -d 3

# Mirror a local file
python mirror_page.py file:///path/to/page.html ./output
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-d, --depth N` | Maximum recursive depth for linked resources | 1 |
| `-r, --referer URL` | Referer header for requests | None |

## 🧪 Testing

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

## 📁 Project Structure

```
mirror-clone/
├── mirror_page.py      # Main script
├── tests/              # Unit and integration tests
├── README.md           # This file
├── AGENTS.md           # Guidelines for AI agents
└── pyproject.toml      # Project metadata and dependencies
```

## 🤖 AI Agent Guidelines

See [AGENTS.md](./AGENTS.md) for development and maintenance guidelines.

## 📄 License

MIT
