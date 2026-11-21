"""The app layer: the shared objects every page works on.

Pages never talk to each other or reach into the engine. They read and change
objects here; every view showing an object hears about the change. No Qt in this
layer, so it can be tested (and scripted) without a window.
"""
