# retry stops one attempt early and hides the failure

retry(fn, 3) calls fn only twice, and if every call fails it returns None instead of raising.

It should call fn up to `attempts` times and return the result of the first call that succeeds. If every attempt fails, raise the exception from the last attempt. attempts below 1 should raise ValueError.
