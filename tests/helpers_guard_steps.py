import os
import time


def quick(x):
    return x * 2


def hang():
    time.sleep(600)


def boom():
    raise ValueError("injected fault")


def die():
    os._exit(9)


def big(n):
    return "x" * n
