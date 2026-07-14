"""Provider-neutral helpers shared by integration broker processes.

The package covers broker lifecycle conventions such as ready signals and exit
codes, plus reusable protocol interpretation such as MIME body rendering.
Concrete brokers import the required submodules directly; this package root is
descriptive rather than a public facade.
"""
