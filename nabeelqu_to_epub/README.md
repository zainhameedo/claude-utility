# nabeelqu_to_epub

Saves every essay on [nabeelqu.co](https://nabeelqu.co/) as its own EPUB, with images embedded, for offline reading on a reMarkable.

```sh
pip install requests beautifulsoup4 readability-lxml lxml_html_clean ebooklib
python nabeelqu_to_epub.py --list   # check which pages it found
python nabeelqu_to_epub.py          # writes ./nabeelqu-epubs/*.epub
```

If `--list` picks up a non-essay page or misses one, put the URLs you want in a text file (one per line) and run `python nabeelqu_to_epub.py --urls essays.txt`.

Then drag the `.epub` files into the reMarkable desktop app or my.remarkable.com.
