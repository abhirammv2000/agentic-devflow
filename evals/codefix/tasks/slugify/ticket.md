# Slugs have stray and repeated hyphens

slugify("  Hello,   World!  ") returns "--hello---world--". It should return "hello-world".

Runs of characters that are not letters or digits should become one hyphen, and there should be no hyphen at the start or the end of the slug.
