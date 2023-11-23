# pylint: disable=invalid-name,redefined-builtin


extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.coverage",
    "sphinx.ext.doctest",
    "sphinx.ext.extlinks",
    "sphinx.ext.ifconfig",
    "sphinx.ext.napoleon",
    "sphinx.ext.todo",
    "sphinx.ext.viewcode",
]
source_suffix = ".rst"
master_doc = "index"
project = "pre-commit-vauxoo"
year = "2022"
author = "Vauxoo"
copyright = "{}, {}".format(year, author)
version = release = "8.0.0"

pygments_style = "trac"
templates_path = ["."]
extlinks = {
    "issue": ("https://github.com/Vauxoo/pre-commit-vauxoo/issues/%s", "#"),
    "pr": ("https://github.com/Vauxoo/pre-commit-vauxoo/pull/%s", "PR #"),
}

html_theme = "sphinx_rtd_theme"
html_use_smartypants = True
html_last_updated_fmt = "%b %d, %Y"
html_split_index = False
html_sidebars = {
    "**": ["searchbox.html", "globaltoc.html", "sourcelink.html"],
}
html_short_title = "%s-%s" % (project, version)

napoleon_use_ivar = True
napoleon_use_rtype = False
napoleon_use_param = False
