# Mirror Clone

A robust, modern web page mirror utility that downloads HTML pages and all their linked resources to a local directory.

This was created because old mirror utilities did not work as expected. They either mangled names, added unwanted comments, copied too much, had too many options, or were not aware of js module includes or modern image formats like webp. This works at least as far as making a convincing local copy of my website and its files. (But of course no mirror utility is able to breach security and clone "back-end" secrets that are properly hidden from the public, such as databases, and server-side code. This would be the ultimate hacker tool if it could.)

## 🚀 Features

- **Recursive Download**: Follows links to download resources up to a configurable depth
- **Connection Pooling**: Efficient HTTP connections via `requests.Session`
- **Retry Logic**: Automatic retries for transient failures (500-504, 429)
- **Depth Control**: Prevents runaway downloads with configurable recursion limit
- **Single-Page Mode**: Only fetch assets needed to render one page
- **Referer Support**: Bypass origin-checking servers with custom referer headers
- **file:// Support**: Handles local file paths alongside HTTP/HTTPS URLs
- **Graceful Error Handling**: Specific handlers for timeouts &amp; connection errors
- **Duplicate Prevention**: Tracks processed URLs to avoid redundant downloads

## 📦 Installation

```bash
# Clone the repository
git clone https://github.com/themanyone/mirror_clone.git
cd mirror_clone

# Make executable
chmod +x mirror_clone.py

# Run
./mirror_clone.py https://example.com ./output -d 2 -r "https://example.com"
```

## 🛠️ Usage

```bash
# Basic usage
python mirror_clone.py https://example.com ./mirror

# With referer header (bypasses origin checks)
python mirror_clone.py https://example.com ./mirror -r "https://example.com"

# Recursive download up to depth 3
python mirror_clone.py https://example.com ./mirror -d 3

# Single-page mode: only the assets this one page needs to render
python mirror_clone.py https://example.com ./mirror --single-page

# Mirror a local html file, along with what it needs.
python mirror_clone.py file:///path/to/page.html ./output
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `-d, --depth N` | Maximum recursive depth for linked resources | 1 |
| `-r, --referer URL` | Referer header for requests (bypasses origin checks) | None |
| `--single-page` | Download only the resources for one page | off |
| `--no-verify` | Disable TLS certificate verification (e.g. self-signed certs) | off |

## 🧪 Testing

```bash
# Run tests
pytest tests/ -v

# Run with coverage
pytest tests/ --cov=. --cov-report=html
```

## 📁 Project Structure

```
mirror_clone/
├── mirror_clone.py      # Main script
├── tests/              # Unit and integration tests
├── README.md           # This file
├── AGENTS.md           # Guidelines for AI agents
└── pyproject.toml      # Project metadata and dependencies
```

## 🤖 AI Agent Guidelines (also helpful for humans)

See [AGENTS.md](./AGENTS.md) for development and maintenance guidelines.

## Thanks for trying out mirror_clone!

- GitHub https://github.com/themanyone
- YouTube https://www.youtube.com/themanyone
- Mastodon https://mastodon.social/@themanyone
- Linkedin https://www.linkedin.com/in/henry-kroll-iii-93860426/
- Buy me a coffee https://buymeacoffee.com/isreality
- [TheNerdShow.com](http://thenerdshow.com/)

Copyright (C) 2026 Henry Kroll III, www.thenerdshow.com.
See the included MIT [LICENSE](LICENSE) for details.
