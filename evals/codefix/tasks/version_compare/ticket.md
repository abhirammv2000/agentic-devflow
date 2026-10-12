# Version 1.10 sorts before 1.9

compare_versions("1.10.0", "1.9.0") returns -1, but 1.10.0 is the newer version.

Versions are dotted whole numbers and should be compared number by number. A missing trailing part counts as zero, so "1.2" and "1.2.0" are equal. The function returns -1, 0 or 1 when the first version is older than, equal to or newer than the second.
