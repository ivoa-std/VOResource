#!/usr/bin/env python

"""
A little script to convert the CSV input format to various outputs.

Dependencies: python2, rapper.

This is re-using ideas of Norman Gray, applied to the datalink vocabulary, 
but adapted for the present case with multiple vocabularies.

We work from a configuration file for vocabularies.  It is written in
ini style, where each section corresponds to a vocabulary.  All items
are mandatory.  Here's how to configure a vocabulary myterms::

	[myterms]
	baseuri: "http://www.ivoa.net/rdf/myterms"
	timestamp: 2016-08-17
	title: My terms as an example
	description: This is a collection of terms not actually used 
		anywhere.  But then, the CSV we're referencing in a moment
		doesn't exist either.
	authors: John Doe; Fred Flintstone

The actual terms are expected in a file <section name>.terms (in the example,
this would be myterms.csv).  It must be a CSV file with the following columns:

	predicate; level; label; description; synonym

level is 1 for "root" terms, 2 for child terms, etc.
synonym, is given, references the "canonical" term for the concept.
synonym can be left out.  Note that we use the semicolon as the
delimiter because description frequently has commas in it and we don't
want to do too much quoting.  Non-ASCII is allowed in label and description;
files must be in UTF-8.

This program is in the public domain.

In case of problems, please contact Markus Demleitner 
<msdemlei@ari.uni-heidelberg.de>
"""

from ConfigParser import ConfigParser
from xml.etree import ElementTree as etree

import contextlib
import csv
import os
import re
import subprocess
import textwrap
import sys


MANDATORY_KEYS = frozenset([
	"baseuri", "timestamp", "title", "description", "authors"])

HT_ACCESS_TEMPLATE = """# .htaccess for content negotiation

# This file is patterned after Recipe 3 in the W3C document 'Best
# Practice Recipes for Publishing RDF Vocabularies', at
# <http://www.w3.org/TR/swbp-vocab-pub/>

AddType application/rdf+xml .rdf
AddType text/turtle .ttl
AddCharset UTF-8 .ttl
AddCharset UTF-8 .html

RewriteEngine On
RewriteBase {install_base}

RewriteCond %{{HTTP_ACCEPT}} application/rdf\+xml
RewriteRule ^$ {timestamp}/{name}.rdf [R=303]

RewriteCond %{{HTTP_ACCEPT}} text/turtle
RewriteRule ^$ {timestamp}/{name}.ttl [R=303]

# No accept conditions: make the .html version the default
RewriteRule ^$ {timestamp}/{name}.html [R=303]
"""


TTL_HEADER_TEMPLATE = """@base {baseuri}.
@prefix : <#>.

@prefix dc: <http://purl.org/dc/terms/> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix foaf: <http://xmlns.com/foaf/0.1/>.

<> a owl:Ontology;
	dc:created {timestamp};
	dc:creator {creators};
	rdfs:label {title}@en;
	dc:title {title}@en;
	dc:description {description}.

dc:created a owl:AnnotationProperty.
dc:creator a owl:AnnotationProperty.
dc:title a owl:AnnotationProperty.
dc:description a owl:AnnotationProperty.
"""


CSS_STYLE = """
html {
	font-family: sans;
}

h1 {
	margin-bottom: 3ex;
	border-bottom: 2pt solid #ccc;
}

tr {
	padding-top: 2pt;
	padding-bottom: 2pt;
	border-bottom: 1pt solid #ccc;
}

thead tr {
	border-top: 1pt solid black;
	border-bottom: 1pt solid black;
}

th {
	padding: 4pt;
}

.intro {
	max-width: 30em;
	margin-bottom: 5ex;
	margin-left: 2ex;
}

.outro {
	max-width: 30em;
	margin-top: 4ex;
}

table {
	border-collapse: collapse;
	border-bottom: 1pt solid black;
}

td {
	vertical-align: top;
	padding: 2pt;
}

th:nth-child(1),
td:nth-child(1) {
  background: #eef;
}

th:nth-child(3),
td:nth-child(3) {
  background: #eef;
  max-width: 20em;
}
"""


class ReportableError(Exception):
	"""is raised for expected and explainable error conditions.

	All other exceptions lead to tracbacks for further debugging.
	"""


############ some utility functions

@contextlib.contextmanager
def work_dir(dir_name):
	"""a context manager for temporarily working in dir_name.

	dir_name, if non-existing, is created.
	"""
	if not os.path.isdir(dir_name):
		os.makedirs(dir_name)
	owd = os.getcwd()
	os.chdir(dir_name)
	try:
		yield
	finally:
		os.chdir(owd)


def is_URI(s):
	"""returns True if we believe s is a URI.

	This is a simple, RE-based heuristic.
	"""
	return bool(re.match("[a-zA-Z]+://|#", s))


############ tiny DOM start (snarfed and simplified from DaCHS stanxml)
# (used to write HTML)

class _Element(object):
		"""An element within a DOM.

		Essentially, this is a simple way to build elementtrees.  You can
		reach the embedded elementtree Element as node.

		Add elements, sequences, etc, using indexation, attributes using function
		calls; names with dashes are written with underscores, python
		reserved words have a trailing underscore.
		"""
		_generator_t = type((x for x in ()))

		def __init__(self, name):
				self.node = etree.Element(name)

		def add_text(self, tx):
				"""appends tx either the end of the current content.
				"""
				if len(self.node):
						self.node[-1].tail = (self.node[-1].tail or "")+tx
				else:
						self.node.text = (self.node.text or "")+tx

		def __getitem__(self, child):
				if child is None:
						return

				elif isinstance(child, basestring):
						self.add_text(child)

				elif isinstance(child, (int, float)):
						self.add_text(str(child))

				elif isinstance(child, _Element):
						self.node.append(child.node)

				elif isinstance(child, (list, tuple, self._generator_t)):
						for c in child:
								self[c]
				else:
						raise Exception("%s element %s cannot be added to %s node"%(
								type(child), repr(child), self.node.tag))
				return self
		
		def __call__(self, **kwargs):
				for k, v in kwargs.iteritems():
						if k.endswith("_"):
								k = k[:-1]
						k = k.replace("_", "-")
						self.node.attrib[k] = v
				return self

		def dump(self, encoding="utf-8", dest_file=sys.stdout):
			etree.ElementTree(self.node).write(dest_file)


class _T(object):
		"""a very simple templating engine.

		Essentially, you get HTML elements by saying T.elementname, and
		you'll get an _Element with that tag name.

		This is supposed to be instanciated to a singleton (here, T).
		"""
		def __getattr__(self, key):
				return  _Element(key)

T = _T()


############ The term class and associated code

def make_ttl_literal(ob):
	"""returns a turtle literal for an object.

	Really, at this point only strings are supported.  However, if something
	looks like a URI (see is_URI), it's going to be treated as a URI.
	"""
	assert isinstance(ob, basestring)
	if is_URI(ob):
		return "<{}>".format(ob)
	else:
		if "\n" in ob:
			return '"""{}"""'.format(ob.encode("utf-8"))
		else:
			return '"{}"'.format(ob.encode("utf-8").replace('"', '\\"'))


class Term(object):
	"""A term in our vocabulary.

	These have predicate, label, description, parent, synonym attributes
	and are constructed with arguments in that order.  parent and synonym
	can be left out.
	"""
	def __init__(self, predicate, label, description, parent=None,
			synonym=None):
		self.predicate, self.label = predicate, label
		self.description, self.parent = description, parent
		self.synonym = synonym

	def as_ttl(self):
		"""returns a turtle representation of this term in a string.
		"""
		fillers = {
			"predicate": self.predicate,
			"label": make_ttl_literal(self.label),
			"comment": make_ttl_literal(self.description),
			}
		template = [
			"<#{predicate}> a rdf:Property",
			"rdfs:label {label}",
			"rdfs:comment {comment}"]

		if self.parent:
			template.append("rdfs:subPropertyOf {parent}")
			fillers["parent"] = make_ttl_literal(self.parent)

		if self.synonym:
			template.append("owl:equivalentProperty {synonym}")
			template.append("a owl:DeprecatedProperty")
			fillers["synonym"] = make_ttl_literal(self.synonym)

		return ";\n  ".join(template).format(**fillers)+"."

	def as_html(self):
		"""returns elementtree for an HTML table line for this term.
		"""
		return T.tr[
			T.td(class_="predicate")[self.predicate],
			T.td(class_="label")[self.label],
			T.td(class_="description")[self.description],
			T.td(class_="parent")[self.parent or ""],
			T.td(class_="preferred")[self.synonym or ""],]


########### Parsing our input files, generating our output files

def _make_vocab_meta(parser, vocab_name):
	"""returns a vocabulary dictionary for vocab_name from a ConfigParser
	instance parser.

	This makes sure all the necessary keys are present and that the
	implied terms file is readable; also, it generates the terms file
	name.
	"""
	vocab_def = dict(parser.items(vocab_name))
	missing_keys = MANDATORY_KEYS-set(vocab_def)
	if missing_keys:
		raise ReportableError("Vocabulary definition for {} incomplete:"
			" {} missing.".format(vocab_name, ", ".join(missing_keys)))

	vocab_def["name"] = vocab_name
	vocab_def["terms_fname"] = vocab_name+".terms"

	try:
		with open(vocab_def["terms_fname"]) as f:
			_ = f.read()
	except IOError:
		raise ReportableError(
			"Expected terms file {}.terms cannot be read.".format(
				vocab_def["terms_fname"]))
	
	return vocab_def


def read_meta(input_name):
	"""reads the vocabulary configuration and returns a sequence
	of vocabulary definition dicts.
	"""
	parser = ConfigParser()
	try:
		with open(input_name) as f:
			parser.readfp(f)
	except IOError:
		raise ReportableError(
			"Cannot open or read vocabulary configuration {}".format(input_name))
	
	meta = []
	for vocab_name in parser.sections():
		meta.append(_make_vocab_meta(parser, vocab_name))
	return meta


def add_rdf_file(turtle_name):
	"""uses rapper to turn our generated turtle file into a suitably named
	RDF file.
	"""
	with open(turtle_name[:-3]+"rdf", "w") as f:
		rapper = subprocess.Popen(["rapper", "-iturtle", "-ordfxml",
				turtle_name],
			stdout=f,
			stderr=subprocess.PIPE)
		_, msgs = rapper.communicate()

	if rapper.returncode!=0:
		sys.stderr.write("Output of the failed rapper run:\n")
		sys.stderr.write(msgs)
		raise ReportableError("Conversion to RDF+XML failed; see output above.")
	

def write_ontology(vocab_def, terms):
	"""writes a turtle file for terms into the current directory.

	The file will be called vocab_def["name"].ttl.
	"""
	with open(vocab_def["name"]+".ttl", "w") as f:
		meta_items = dict((k, make_ttl_literal(v))
			for k, v in vocab_def.items())
		meta_items["creators"] = ",\n    ".join(
				'[ foaf:name {} ]'.format(make_ttl_literal(n.strip()))
			for n in vocab_def["authors"].split(";"))
		f.write(TTL_HEADER_TEMPLATE.format(**meta_items))

		for term in terms:
			f.write(term.as_ttl())
			f.write("\n\n")
	
	add_rdf_file(vocab_def["name"]+".ttl")


def write_html(vocab_def, terms):
	"""writes an HTML-format documentation for terms into the current
	directory.

	The file will be called vocab_def["name"].html.
	"""
	term_table = T.table(class_="terms")[
		T.thead[
			T.tr[
				T.th(title="The formal name of the predicate as used in URIs"
					)["Predicate"],
				T.th(title="Suggested label for the predicate in human-facing UIs"
					)["Label"],
				T.th(title="Human-readable description of the predicate"
					)["Description"],
				T.th(title="If the predicate is in a wider-narrower relationship"
					" to other predicates: The more general term.")["Parent"],
				T.th(title="If the predicate has been superseded by another"
					" term but is otherwise synonymous with it: The term that"
					" should now be preferentially used")["Preferred"],
			],
		],
		T.tbody[
			[t.as_html() for t in terms]
		]
	]

	doc = T.html(xmlns="http://www.w3.org/1999/xhtml")[
		T.head[
			T.title["IVOA Vocabulary: "+vocab_def["title"]],
			T.meta(http_equiv="content-type", 
				content="text/html;charset=utf-8"),
			T.style(type="text/css")[
				CSS_STYLE],],
		T.body[
			T.h1["IVOA Vocabulary: "+vocab_def["title"]],
			T.div(class_="intro")[
				T.p["This is the description of the namespace ",
					T.code[vocab_def["baseuri"]],
				" as of {}.".format(vocab_def["timestamp"])],
				T.p(class_="description")[vocab_def["description"]]],
			term_table,
			T.p(class_="outro")["Alternate formats: ",
				T.a(href=vocab_def["name"]+".rdf")["RDF"],
				", ",
				T.a(href=vocab_def["name"]+".ttl")["Turtle"],
				"."]]]

	with open(vocab_def["name"]+".html", "w") as f:
		doc.dump(dest_file=f)


def write_htaccess(vocab_def, root_url):
	"""writes a customised .htaccess for content negotiation.

	This must be called one level up from the ttl and html files.
	"""
	with open(".htaccess", "w") as f:
		f.write(HT_ACCESS_TEMPLATE.format(
			install_base=vocab_def["baseuri"]+"/",
			timestamp=vocab_def["timestamp"],
			name=vocab_def["name"]))


def write_meta_inf(vocab_def):
	"""writes a "short" META.INF for use by the vocabulary TOC generator
	at the IVOA web page to the current directory.
	"""
	with open("META.INF", "w") as f:
		f.write("Name: {}\n{}\n".format(
		vocab_def["title"],
		textwrap.fill(
			vocab_def["description"], 
			initial_indent="Description: ",
			subsequent_indent="  ")))


def parse_terms(src_name):
	"""returns a sequence of Terms from a CSV input.
	"""
	parent_stack = []
	last_predicate = None
	terms = []
	with open(src_name) as f:
		for rec in csv.reader(f, delimiter=";"):
			rec = [(s or None) for s in rec]

			hierarchy_level = int(rec[1])
			if hierarchy_level-1>len(parent_stack):
				parent_stack.append(last_predicate)
			while hierarchy_level-1<len(parent_stack):
				parent_stack.pop()
			last_predicate = rec[0]
			if not is_URI(last_predicate):
				last_predicate = "#"+last_predicate

			if parent_stack:
				parent = parent_stack[-1]
			else:
				parent = None

			if len(rec)<5:
				synonym = None
			else:
				synonym = rec[4]
				if not is_URI(synonym):
					synonym = "#"+synonym

			terms.append(
				Term(rec[0], rec[2].decode("utf-8"), 
					rec[3].decode("utf-8"), parent, synonym))
	
	return terms


def build_vocab(vocab_def, install_root):
	"""builds, in a subdirectory named <name>/<timestamp>, all files
	necessary on the server side.

	It also puts an .htaccess into the <name>/ directory that will redirect 
	clients to the appropriate files of this release based using content 
	negotiation.

	install_root is the URI of the directory the result will reside in.
	"""
	try:
		terms = parse_terms(vocab_def["terms_fname"])
	except:
		sys.stderr.write(
			"The following error was raised from within {}:\n".format(
				vocab_def["terms_fname"]))
		raise
	dest_dir = "{}/{}".format(vocab_def["name"], vocab_def["timestamp"])

	with work_dir(dest_dir):
		write_ontology(vocab_def, terms)
		write_html(vocab_def, terms)

	with work_dir(vocab_def["name"]):
		write_htaccess(vocab_def, install_root)
		write_meta_inf(vocab_def)


def parse_command_line():
	import argparse
	parser = argparse.ArgumentParser(
		description='Creates RDF, HTML and turtle files for a set of vocabularies.')
	parser.add_argument("vocab_config", 
		help="Name of the vocabularies configuration file.",
		type=str)
	parser.add_argument("--install-root", 
		help="Use URI instead of"
		" the official IVOA location as the root of the vocabulary"
		" hierarchy.  This is for test installations.",
		action="store", 
		dest="install_root", 
		default="http://www.ivoa.net/std/rdf/",
		metavar="URI")
	args = parser.parse_args()
	
	if not args.install_root.endswith("/"):
		args.install_root = args.install_root+"/"
	
	return args


def main():
	args = parse_command_line()
	if args.install_root!="http://www.ivoa.net/std/rdf/":
		# to make this work again, you'd need to infer the local part of
		# the URI from the baseuri above.
		raise ReportableError("Non-official install_roots not currently"
			" supported, sorry.")
	meta = read_meta(args.vocab_config)
		
	for vocab_def in meta:
		build_vocab(vocab_def, args.install_root)


if __name__=="__main__":
	try:
		main()
	except ReportableError, msg:
		sys.stderr.write("*** Fatal: {}\n".format(msg))
		sys.exit(1)
