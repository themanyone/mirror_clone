# AI Agent Guidelines for Mirror Clone

This document provides guidelines and context for AI agents working with the mirror-clone project.

## 🎯 Project Purpose

Mirror Clone is a web page mirroring utility that downloads HTML pages and their linked resources to a local directory. It's designed for:
- Archiving web pages with all assets
- Offline documentation
- Content preservation
- Development testing

## 📋 Key Files

| File | Purpose |
|------|---------|
| `mirror_clone.py` | Main CLI tool - handles URL validation, HTTP requests, resource extraction, and file downloads |
| `tests/` | Unit and integration tests for core functionality |
| `pyproject.toml` | Project metadata, dependencies, and build configuration |

## 🔧 Technical Stack

- **Language**: Python 3.8+
- **Core Library**: `requests` (HTTP client)
- **Retry Logic**: `urllib3` (via requests)
- **Testing**: `pytest`

## 🧪 Testing Philosophy

Tests should cover:
1. **URL validation** - Accept/reject various URL formats
2. **Resource extraction** - Parse HTML for href/src attributes
3. **Download handling** - Success, timeout, connection errors, non-200 responses
4. **Depth limiting** - Prevent infinite recursion
5. **Duplicate prevention** - Set-based tracking works correctly

## 🤖 AI Agent Guidelines

### When modifying code:
- **Preserve docstrings**: All public functions must have clear documentation
- **Maintain error handling**: Don't remove try/except blocks; improve them if needed
- **Add type hints**: Use Python 3.8+ type annotations for clarity
- **Follow existing style**: 4-space indentation, single quotes for strings

### When adding features:
- **Backward compatibility**: Don't break existing CLI arguments
- **Graceful degradation**: Handle edge cases without crashing
- **Logging**: Use `print()` for CLI feedback; consider `logging` for production

### When debugging:
- **Reproduce first**: Verify the issue with minimal test case
- **Isolate**: Change one thing at a time
- **Test incrementally**: Run tests after each change

### Common pitfalls to avoid:
- ❌ Don't use `file://` with HTTP requests (they're handled separately)
- ❌ Don't download the same resource twice (use the `seen` set)
- ❌ Don't forget to close sessions (use `finally` blocks)
- ❌ Don't assume UTF-8 encoding (use response encoding fallback)

## 📊 Performance Considerations

- Connection pooling reduces overhead for multiple requests
- Rate limiting (100ms delay) prevents server overload
- Depth limiting prevents runaway downloads
- Duplicate tracking avoids redundant network I/O

## 🔐 Security Notes

- Never download from untrusted sources without validation
- Respects HTTP headers (Content-Type, Referer)
- No arbitrary code execution from downloaded content
- Session is properly closed to prevent resource leaks

## 🚀 Launch Checklist

Before deploying or sharing:
- [ ] Run `pytest tests/ -v` - all tests pass
- [ ] Test with a real URL (e.g., `https://example.com`)
- [ ] Verify output directory structure
- [ ] Check that all linked resources are downloaded
- [ ] Confirm depth limiting works (`-d 1` vs `-d 3`)
- [ ] Test error handling (invalid URL, network failure)
