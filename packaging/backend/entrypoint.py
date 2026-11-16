"""PyInstaller entry point; package imports remain absolute."""
if __name__ == '__main__':
    from multiprocessing import freeze_support
    freeze_support()
    from src.runtime.local_service import main
    main()
