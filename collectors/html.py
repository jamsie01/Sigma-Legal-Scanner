"""Small HTML tree using only the Python standard library."""
from html.parser import HTMLParser


class Node:
    def __init__(self, tag='', attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, {}, parent
        # HTML uses the first occurrence of a duplicate attribute. TLT's
        # search form currently contains two id attributes.
        for key, value in attrs:
            self.attrs.setdefault(key, value)
        self.children = []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Node):
                yield from child.walk()

    def find(self, tag=None, cls=None, id=None):
        return [n for n in self.walk()
                if (tag is None or n.tag == tag)
                and (cls is None or cls in n.attrs.get('class', '').split())
                and (id is None or n.attrs.get('id') == id)]

    def text(self):
        return ' '.join(' '.join(c.text() if isinstance(c, Node) else c
                                for c in self.children).split())

    def raw(self):
        return ''.join(c.raw() if isinstance(c, Node) else c for c in self.children)


class Tree(HTMLParser):
    VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input',
            'link', 'meta', 'param', 'source', 'track', 'wbr'}

    def __init__(self, html):
        super().__init__(convert_charrefs=True)
        self.root = self.current = Node()
        self.feed(html)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.current)
        self.current.children.append(node)
        if tag not in self.VOID:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        node = self.current
        while node.parent is not None:
            if node.tag == tag:
                self.current = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.current.children.append(data)


def text_field(root, cls):
    matches = root.find(cls=cls)
    return matches[0].text() if matches else ''
