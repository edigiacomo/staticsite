# coding: utf-8

from staticsite.core import Site, load_settings, settings
import sys
import os
import time
import logging

log = logging.getLogger()

class CmdlineError(RuntimeError):
    pass


class SiteCommand:
    # Command name (as used in command line)
    # Defaults to the lowercased class name
    NAME = None

    # Command description (as used in command line help)
    # Defaults to the strip()ped class docstring.
    DESC = None

    def __init__(self, args):
        self.setup_logging(args)

        # Default to current directory if rootdir was not provided
        if args.rootdir:
            self.root = os.path.abspath(args.rootdir)
        else:
            self.root = os.getcwd()

        # Double check that root points to something that looks like a project
        self.site_root = os.path.join(self.root, "site")
        if not os.path.exists(self.site_root):
            raise CmdlineError("{} does not exist".format(self.site_root))

        # Load settings (optional)
        settings_file = os.path.join(self.root, "settings.py")
        if os.path.isfile(settings_file):
            load_settings(settings_file)

    def setup_logging(self, args):
        FORMAT = "%(asctime)-15s %(levelname)s %(message)s"
        if args.debug:
            logging.basicConfig(level=logging.DEBUG, stream=sys.stderr, format=FORMAT)
        elif args.verbose:
            logging.basicConfig(level=logging.INFO, stream=sys.stderr, format=FORMAT)
        else:
            logging.basicConfig(level=logging.WARN, stream=sys.stderr, format=FORMAT)

    def load_site(self):
        # Instantiate site
        site = Site(self.root)

        # Read and analyze site contents
        start = time.perf_counter()
        site.read_tree()
        site.read_theme_asset_tree("theme/static")
        end = time.perf_counter()
        log.info("Read site tree in %fs", end-start)

        start = time.perf_counter()
        site.analyze()
        end = time.perf_counter()
        log.info("Analised site tree in %fs", end-start)

        return site

    @classmethod
    def make_subparser(cls, subparsers):
        name = cls.NAME
        if name is None:
            name = cls.__name__.lower()

        desc = cls.DESC
        if desc is None:
            desc = cls.__doc__.strip()

        parser = subparsers.add_parser(name, help=desc)
        parser.add_argument("rootdir", nargs="?", help="project directory (default: the current directory)")
        parser.add_argument("-v", "--verbose", action="store_true", help="verbose output")
        parser.add_argument("--debug", action="store_true", help="verbose output")
        parser.set_defaults(handler=cls)

        return parser