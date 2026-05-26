import sys, os
print("sys.path:", sys.path[0])
print("sys.path:", os.path.abspath("src") in sys.path)
print("sys.path:", os.path.abspath(".") in sys.path)