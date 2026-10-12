# Commas inside quotes split the field

parse_line('a,"b,c",d') returns four fields. It should return ["a", "b,c", "d"].

A field can be wrapped in double quotes, and then it can contain commas. Inside a quoted field, two double quotes in a row mean one literal quote. Fields that are not quoted are returned exactly as written, with no trimming. An empty line gives [""].
