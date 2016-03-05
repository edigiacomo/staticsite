# coding: utf-8
import os
import sys
import logging
import shutil
import mimetypes
from . import content

log = logging.getLogger()

class Settings:
    def __init__(self):
        from . import global_settings
        self.add_module(global_settings)

    def as_dict(self):
        res = {}
        for setting in dir(self):
            if setting.isupper():
                res[setting] = getattr(self, setting)
        return res

    def add_module(self, mod):
        """
        Add uppercase settings from mod into this module
        """
        for setting in dir(mod):
            if setting.isupper():
                setattr(self, setting, getattr(mod, setting))

    def load(self, pathname):
        """
        Load settings from a python file, importing only uppercase symbols
        """
        orig_dwb = sys.dont_write_bytecode
        try:
            sys.dont_write_bytecode = True
            # http://stackoverflow.com/questions/67631/how-to-import-a-module-given-the-full-path

            # Seriously, this should not happen in the standard library. You do not
            # break stable APIs. You can extend them but not break them. And
            # especially, you do not break stable APIs and then complain that people
            # stick to 2.7 until its death, and probably after.
            if sys.version_info >= (3, 5):
                import importlib.util
                spec = importlib.util.spec_from_file_location("staticsite.settings", pathname)
                user_settings = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(user_settings)
            else:
                from importlib.machinery import SourceFileLoader
                user_settings = SourceFileLoader("staticsite.settings", pathname).load_module()
        finally:
            sys.dont_write_bytecode = orig_dwb

        self.add_module(user_settings)


settings = Settings()



class Archetype:
    def __init__(self, site, relpath):
        self.site = site
        self.relpath = relpath

    def as_template(self, **kw):
        abspath = os.path.join(site.archetypes_root, self.relpath)
        with open(abspath, "rt") as fd:
            return self.site.jinja2.from_string(fd.read(), **kw)


class Page:
    # In what pass must pages of this type be analyzed.
    ANALYZE_PASS = 1

    # True if the page can be found when search site contents
    FINDABLE = False

    # Preferred order of rendering, not for functional purposes for for
    # purposes of collecting reasonable timings. This can be used for example
    # to render markdown pages before taxonomies, so that the time of rendering
    # markdown is counted as such and not as time needed for rendering
    # taxonomies.
    RENDER_PREFERRED_ORDER = 1

    def __init__(self, site, root_abspath, relpath):
        # Site that owns this page
        self.site = site

        # Absolute path of the root on which relpath is rooted
        self.root_abspath = root_abspath

        # Relative path of the page in the source directory, as used to
        # reference the page in links
        self.src_relpath = relpath

        # Relative path used to link to this page in the sources
        self.link_relpath = relpath

        # Relative path of the page in the target directory, as used to
        # generate the output page
        self.dst_relpath = relpath

        # Relative link used to point to this resource in URLs
        self.dst_link = os.path.join(settings.SITE_ROOT, relpath)

        # Page metadata. See README for a list.
        self.meta = {}

    @property
    def src_abspath(self):
        return os.path.join(self.root_abspath, self.src_relpath)

    @property
    def date_as_iso8601(self):
        from dateutil.tz import tzlocal
        ts = self.meta.get("date", None)
        if ts is None: return None
        # TODO: Take timezone from config instead of tzlocal()
        tz = tzlocal()
        ts = ts.astimezone(tz)
        offset = tz.utcoffset(ts)
        offset_sec = (offset.days * 24 * 3600 + offset.seconds)
        offset_hrs = offset_sec // 3600
        offset_min = offset_sec % 3600
        if offset:
            tz_str = '{0:+03d}:{1:02d}'.format(offset_hrs, offset_min // 60)
        else:
            tz_str = 'Z'
        return ts.strftime("%Y-%m-%d %H:%M:%S") + tz_str

    def resolve_link(self, target):
        # Absolute URLs are resolved as is
        if target.startswith("/"):
            target_relpath = os.path.normpath(target.lstrip("/"))
            return self.site.pages.get(target_relpath, None)

        root = os.path.dirname(self.src_relpath)
        while True:
            target_relpath = os.path.normpath(os.path.join(root, target))
            res = self.site.pages.get(target_relpath, None)
            if res is not None: return res
            if not root or root == "/":
                return None
            root = os.path.dirname(root)

    def read_metadata(self):
        """
        Fill in self.meta scanning the page contents
        """
        pass

    def check(self, checker):
        pass

    def target_relpaths(self):
        return [self.dst_relpath]


class RenderedFile:
    def __init__(self, abspath):
        self.abspath = abspath

    def write(self, dst):
        shutil.copy2(self.abspath, dst)

    def content(self):
        with open(self.abspath, "rb") as fd:
            return fd.read()


class RenderedString:
    def __init__(self, s):
        self.buf = s.encode("utf-8")

    def write(self, dst):
        with open(dst, "wb") as out:
            out.write(self.buf)

    def content(self):
        return self.buf


class PageFS:
    """
    VFS-like abstraction that maps the names of files that pages would render
    with the corresponding pages.

    This can be used to render pages on demand.
    """
    def __init__(self):
        self.paths = {}

    def add_site(self, site):
        for page in site.pages.values():
            for relpath in page.target_relpaths():
                self.add_page(page, relpath)

    def add_page(self, page, dst_relpath=None):
        if dst_relpath is None:
            dst_relpath = page.dst_relpath
        self.paths[dst_relpath] = page

    def get_page(self, relpath):
        if not relpath:
            relpath = "/index.html"
        dst_relpath = os.path.normpath(relpath).lstrip("/")
        page = self.paths.get(dst_relpath, None)
        if page is not None:
            return dst_relpath, page

        dst_relpath = os.path.join(dst_relpath, "index.html")
        page = self.paths.get(dst_relpath, None)
        if page is not None:
            return dst_relpath, page

        return None, None

    def serve_path(self, path, environ, start_response):
        """
        Render a page on the fly and serve it.

        Call start_response with the page headers and return the bytes() with
        the page contents.

        start_response is the start_response from WSGI

        Returns None without calling start_response if no page was found.
        """
        dst_relpath, page = self.get_page(os.path.normpath(path).lstrip("/"))
        if page is None: return None

        for relpath, rendered in page.render().items():
            if relpath == dst_relpath:
                break
        else:
            return None

        content = rendered.content()
        start_response("200 OK", [
            ("Content-Type", mimetypes.guess_type(relpath)[0]),
            ("Content-Length", str(len(content))),
        ])
        return [content]
