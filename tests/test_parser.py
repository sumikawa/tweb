import unittest

from tweb.fetcher import Resource
from tweb.parser import parse_document


class ParserTest(unittest.TestCase):
  def test_stray_end_tag_does_not_pop_body_context(self) -> None:
    document = parse_document(
      Resource(
        source="https://example.com",
        content="""
        <html>
          <body>
            <div id="search">
              <div class="pane">
                <dl>
                  <dt>before</dt>
                </div>
                </dl>
              </div>
            </div>
            <div id="contents">
              <p>after</p>
            </div>
          </body>
        </html>
        """,
      )
    )

    body = document.body
    self.assertIsNotNone(body)
    self.assertIsNotNone(body.find_first("p"))
    self.assertEqual(body.find_first("p").text_content(), "after")
    contents = next(
      (node for node in document.find_all("div") if node.attrs.get("id") == "contents"),
      None,
    )
    self.assertIsNotNone(contents)
    self.assertIn(contents, body.children)


if __name__ == "__main__":
  unittest.main()
