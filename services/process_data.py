# modify python path so that this script can be targeted directly but still import everything.
import imp as _imp
from os.path import abspath as _abspath
_current_folder_init = _abspath(__file__).rsplit('/', 1)[0]+ "/__init__.py"
_imp.load_source("__init__", _current_folder_init)
import datetime

from libs.file_processing import process_file_chunks

if __name__ == "__main__":
	print("Running at: " + datetime.datetime.now())
	process_file_chunks()