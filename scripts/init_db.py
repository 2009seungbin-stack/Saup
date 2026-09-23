import argparse
from packages.infrastructure.settings import Settings
from packages.infrastructure.db import database
from packages.application.seed import seed

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--demo',action='store_true');args=parser.parse_args()
    settings=Settings();_,factory=database(settings.database_url)
    seed(settings,factory,demo=args.demo)
    print('Initialized admin and accounts'+(' with SYNTHETIC demo data' if args.demo else ''))
if __name__=='__main__':main()
