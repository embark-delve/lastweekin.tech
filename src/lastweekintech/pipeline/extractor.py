from newspaper import Article as NewspaperArticle, Config
from .ports import ContentExtractor

class NewspaperExtractor(ContentExtractor):
    """
    Extracts the full text content from a URL using the newspaper3k library.
    """
    def extract(self, url: str) -> str:
        """
        Downloads, parses, and extracts the main content of an article.
        """
        try:
            # Using a Config object to set a user-agent and timeout
            config = Config()
            config.browser_user_agent = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'
            config.request_timeout = 10

            article = NewspaperArticle(url, config=config)
            article.download()
            article.parse()
            return article.text
        except Exception as e:
            print(f"Error extracting content from {url}: {e}")
            return ""

if __name__ == '__main__':
    # Test the extractor
    test_url = "https://techcrunch.com/2025/10/25/tiktok-robot-star-rizzbot-gave-me-the-middle-finger/"

    print(f"--- Testing NewspaperExtractor on: {test_url} ---")
    extractor = NewspaperExtractor()
    content = extractor.extract(test_url)

    if content:
        print("Extraction successful!")
        print("\n--- Extracted Content (first 300 chars) ---")
        print(content[:300] + "...")
    else:
        print("Extraction failed.")

    # Test a URL that might fail
    test_fail_url = "https://httpbin.org/status/404"
    print(f"\n--- Testing NewspaperExtractor on a failing URL: {test_fail_url} ---")
    content_fail = extractor.extract(test_fail_url)
    if not content_fail:
        print("Extraction correctly failed as expected.")
    else:
        print("Extraction unexpectedly succeeded.")
