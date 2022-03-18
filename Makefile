# ivoatex Makefile.  The ivoatex/README for the targets available.

# short name of your document (edit $DOCNAME.tex; would be like RegTAP)
DOCNAME = VOResource

# count up; you probably do not want to bother with versions <1.0
DOCVERSION = 1.1

# Publication date, ISO format; update manually for "releases"
DOCDATE = 2018-06-25

# What is it you're writing: NOTE, WD, PR, or REC
DOCTYPE = REC

# Source files for the TeX document (but the main file must always
# be called $(DOCNAME).tex
SOURCES = $(DOCNAME).tex example-voresource.xml role_diagram.pdf

# List of pixel image files to be included in submitted package 
FIGURES = role_diagram.svg

# List of PDF figures (for vector graphics)
VECTORFIGURES = 

# Additional files to distribute (e.g., CSS, schema files, examples...)
AUX_FILES = VOResource-v1.1.xsd terms

AUTHOR_EMAIL=msdemlei@ari.uni-heidelberg.de

-include ivoatex/Makefile

ivoatex/Makefile:
	@echo "*** ivoatex submodule not found.  Initialising submodules."
	@echo
	git submodule update --init

STILTS ?= stilts

# These tests need stilts >3.4 and xmlstarlet
test:
	@sh test-assertions.sh
	@$(STILTS) xsdvalidate VOResource-v1.1.xsd
	@$(STILTS) xsdvalidate \
		schemaloc='http://www.ivoa.net/xml/VOResource/v1.0=VOResource-v1.1.xsd' \
		example-voresource.xml
