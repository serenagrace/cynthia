from multiprocessing import Process, Value, Manager


class Daemon:
    def __init__(self):
        self.run = Value("b", True)
        self.ns = Manager().Namespace()

        self.process = Process(target=self.loop, args=(self.run, self.ns))
        self.process.daemon = True
        self.process.start()
