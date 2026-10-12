# Page 1 skips the first items

paginate(list(range(10)), 1, 3) returns [3, 4, 5]. Pages are numbered from 1, so it should return [0, 1, 2].

A page past the end should give an empty list. A page below 1, or a per_page below 1, should raise ValueError.
