
# Having main separate from __main__ seems nessesary for working editable installs
from .main import main

if __name__ == '__main__':
    main()
