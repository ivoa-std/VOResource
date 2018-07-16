# A shallow wrapper for installing the vocabularies; you for each destination,
# you have to define both a _DEST (where to rsync the material) and a
# _URL_ROOT (where to point a browser to find the root of the vocabulary
# tree generated).
# This isn't pretty yet, but let's see how tricky we want to get here.

#TEST_DEST=alnilam:/var/www/docs/vocab-test
#TEST_URL_ROOT=/vocab-test

BUILT_DIRS=content_level content_type date_role relationship_type

test:
	python convert.py vocabs.conf

test-install:
	python convert.py --install-root $(TEST_URL_ROOT) vocabs.conf
	rsync -av $(BUILT_DIRS) $(TEST_DEST)

clean:
	rm -rf .build_stamp $(BUILT_DIRS)
