#!/usr/bin/env python

"""
A little script to convert the CSV input format to various outputs.

This is re-using ideas of Norman Gray, applied to the datalink vocabulary, 
but adapted for the present case with multiple vocabularies.

We work from a configuration file for vocabularies.  It is written in
ini style, where each section corresponds to a vocabulary.  All items
are mandatory.  Here's how to configure a vocabulary myterms::

	[myterms]
	baseuri: "http://www.ivoa.net/rdf/myterms"
	timestamp: 2016-08-17
	title: My terms as an example
	description: This is a collection of terms not actually used \
		anywhere.  But then, the CSV we're referencing in a moment \
		doesn't exist either.
	authors: John Doe; Fred Flintstone

The actual terms are expected in a file <section name>.terms (in the example,
this would be myterms.csv).  It must be a CSV file with the following columns:

	predicate; level; label; description; synonym

level is 1 for "root" terms, 2 for child terms, etc.
synonym, is given, references the "canonical" term for the concept.
synonym can be left out.  Note that we use the semicolon as the
delimiter because description frequently has commas in it and we don't
want to do too much quoting.

This program is in the public domain.

In case of problems, please contact Markus Demleitner 
<msdemlei@ari.uni-heidelberg.de>
"""

# The central data structure here is meta, a list of vocabulary defintion
# dictionaries.  Each dict maps the items in the config to their values;
# in addition, the have name and terms_fname keys built from the
# section names in the config file.


from ConfigParser import ConfigParser
import contextlib
import csv
import os
import re
import sys


MANDATORY_KEYS = frozenset([
	"baseuri", "timestamp", "title", "description", "authors"])

TTL_HEADER_TEMPLATE = """@base {baseuri}
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


class ReportableError(Exception):
	"""is raised for expected and explainable error conditions.

	All other exceptions lead to tracbacks for further debugging.
	"""


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
	return bool(re.match("[a-zA-Z]://|#", s))


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
			return '"""{}"""'.format(ob)
		else:
			return '"{}"'.format(ob.replace('"', '\\"'))


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
			"<#{predicate}> a rdf:Property;",
			"  rdfs:label {label};",
			"  rdfs:comment {comment};"]

		if self.parent:
			template.append("  rdfs.subPropertyOf {parent}")
			fillers["parent"] = make_ttl_literal(self.parent)

		if self.synonym:
			template.append("  rdfs.synonymOf {synonym}")
			fillers["parent"] = make_ttl_literal(self.synonym)

		return "\n".join(template).format(**fillers)+"."


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


def write_ontology(vocab_def, terms):
	"""write a turtle file for terms into the current directory.

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
				synonym = rec[5]

			terms.append(
				Term(rec[0], rec[2], rec[3], parent, synonym))
	
	return terms


def build_vocab(vocab_def):
	"""builds, in a subdirectory named vocab_def["name"], all files
	necessary on the server side.
	"""
	terms = parse_terms(vocab_def["terms_fname"])
	with work_dir(vocab_def["name"]):
		write_ontology(vocab_def, terms)


def parse_command_line():
	import argparse
	parser = argparse.ArgumentParser(
		description='Creates RDF, HTML and turtle files for a set of vocabularies.')
	parser.add_argument("vocab_config", 
		help="Name of the vocabularies configuration file.",
		type=str)
	return parser.parse_args()


def main():
	args = parse_command_line()
	meta = read_meta(args.vocab_config)
		
	for vocab_def in meta:
		build_vocab(vocab_def)


if __name__=="__main__":
	try:
		main()
	except ReportableError, msg:
		sys.stderr.write("*** Fatal: {}\n".format(msg))
		sys.exit(1)
