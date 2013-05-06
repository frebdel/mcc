'''
Created on 17.10.2012

@author: frederic
'''

import os
#import scipy as sp
#from utils import normsq
#from classAgent import Agent
#from sim import States
#import classMaze
import constants, utils

class Mesenchymal():
    '''
    Represents an agent that can use his energy to degrade walls. Inherits from Agent.
    '''
    
    classInitialized = False
    eat = None
    z = 0.0
    degrad_rate = 0.0
    safety_factor = 1.0
    
#    def __init__(self, i, pos, vel, E, state, statechange, const, m = None, period = None, delay = None):
#        if Mesenchymal.classInitialized==False:
#            Mesenchymal.classInit(const)            
#        Agent.__init__(self, i, pos, vel, E, const, m, state, statechange=statechange, period=period, delay=delay)
        
    @staticmethod
    def classInit(const, basepath=None):
        if basepath is None:
            basepath = os.getcwd()
        eatpath = os.path.join(basepath, constants.resourcespath, const["eatshape"])
        Mesenchymal.eat = utils.loadImage(eatpath)
        Mesenchymal.eat = utils.scaleToMax(constants.wallconst, Mesenchymal.eat)
        Mesenchymal.degrad_rate = const["zeta"] #* sp.mean(Mesenchymal.eat)
        Mesenchymal.safety_factor = const["safety_factor"]
        Mesenchymal.classInitialized = True
    
    @staticmethod
    def getMaxEatingDistance(density):
        shape = tuple(map(round, (1/density) * Mesenchymal.eat.shape))
        return 0.5 * Mesenchymal.safety_factor * max(shape)
