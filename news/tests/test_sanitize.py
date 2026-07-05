from django.test import SimpleTestCase

from news.sanitize import clean_html


class CleanHtmlTests(SimpleTestCase):
    def test_script_removed(self):
        self.assertEqual(clean_html('<p>ok</p><script>alert(1)</script>'), '<p>ok</p>')

    def test_event_handler_stripped(self):
        self.assertNotIn('onclick', clean_html('<p onclick="x()">t</p>'))

    def test_javascript_url_stripped(self):
        out = clean_html('<a href="javascript:alert(1)">x</a>')
        self.assertNotIn('javascript:', out)

    def test_allowed_markup_kept(self):
        src = ('<h2>Заголовок</h2><p class="ql-align-center"><strong>ж</strong> '
               '<em>к</em> <u>п</u> <s>з</s></p><ol><li>раз</li></ol>'
               '<ul><li>а</li></ul><blockquote>цитата</blockquote>')
        out = clean_html(src)
        for frag in ('<h2>', '<strong>', '<em>', '<u>', '<s>', '<ol>', '<ul>',
                     '<li>', '<blockquote>', 'ql-align-center'):
            self.assertIn(frag, out)

    def test_https_link_kept_with_rel(self):
        out = clean_html('<a href="https://example.com">x</a>')
        self.assertIn('href="https://example.com"', out)
        self.assertIn('noopener', out)

    def test_empty_input(self):
        self.assertEqual(clean_html(''), '')
        self.assertEqual(clean_html(None), '')
