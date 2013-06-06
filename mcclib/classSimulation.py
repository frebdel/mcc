import os, datetime, shutil
import numpy as np
import scipy.weave as weave
import scipy.weave.converters as converters
from classMesenchymal import Mesenchymal
from classMaze import Maze, densityArray
from classDataset import Dataset
import statutils
import sim
import utils
from utils import info
import constants

class Simulation:
    
    def __init__(self, const, noDelete=False):
        """Constructs the ``Simulation`` object according to ``const`` and creates an empty directory for the results."""
        self.const = const
        
        self.path = os.getcwd() + "/"
        self.resultsdir = os.path.join(self.path, constants.resultspath, const["name"])
        
        if not os.path.exists(self.resultsdir):
            os.mkdir(self.resultsdir)
        if noDelete==False:
            utils.makeFolderEmpty(self.resultsdir)
            
        self.N_amoeboid = self.const["N_amoeboid"]
        self.N_mesenchymal = self.const["N_mesenchymal"]
        self.N = self.N_amoeboid + self.N_mesenchymal
        self.NNN = int(const["max_time"] / const["dt"])
        
        self.retainCompleteDataset = utils.retainCompleteDataset(const)
        
        if noDelete==False:
            self.dsA = Dataset(Dataset.AMOEBOID, const["max_time"], const["dt"], self.N, constants.DIM, self.resultsdir, fileprefix=None)
            if self.retainCompleteDataset:
                info("Created dataset of size %s" % self.dsA.getHumanReadableSize())
            else:
                info("Created temporary dataset of size %s" % self.dsA.getHumanReadableSize())
    
    #@profile
    def run(self):
        """Actually runs the simulation and saves the results according to ``const``."""
        logfilepath = utils.getResultsFilepath(self.resultsdir, "logfile.txt")
        logging_handler = utils.setup_logging_sim(logfilepath)

        useWeave = constants.useWeave          
        t_start = datetime.datetime.now()
        DIM = constants.DIM
        N = self.N
        N_mesenchymal = self.N_mesenchymal
        N_amoeboid = self.N_amoeboid
        NNN = self.NNN
        dt = self.const["dt"]
        goal = np.array(self.const["gradientcenter"])
        initial_position = np.array(self.const["initial_position"])
        stray = np.array(self.const["initial_position_stray"])
        assert stray>0, "Unfortunately you have to use a stray>0."
        
        info("Simulation started with %s agents" % N)
        
        #prepare landscape
        mazepath = os.path.join(self.path, self.const["maze"])
        myMaze = Maze(mazepath, self.const["fieldlimits"], self.const["border"], useWeave=constants.useWeave)
        maze = myMaze.data
        density = densityArray(maze.shape, self.const["fieldlimits"])
        #prepare gradient
        goal_px = np.array(density * goal, dtype=np.int_)
        concentrationfield = np.fromfunction(lambda x, y: utils.concentration(x, y, goal_px), (maze.shape))        
        #or null field
        #concentrationfield = np.ones((x_max, y_max))
        cgrad = utils.getGradient(concentrationfield)
        
        #initialize agents
        self.dsA.types = np.array(N_mesenchymal*[Dataset.is_mesenchymal]+N_amoeboid*[Dataset.is_amoeboid])
        isMesenchymal = self.dsA.types==Dataset.is_mesenchymal
        isAmoeboid = self.dsA.types==Dataset.is_amoeboid
        self.dsA.velocities[0] = np.zeros((N, DIM))
        self.dsA.energies[0] = 0.0
        self.dsA.states[0] = sim.States.MOVING
        period = self.const["orientationperiod"] + np.random.standard_normal(N) * self.const["periodsigma"]
        delay = self.const["orientationdelay"] + np.random.standard_normal(N) * self.const["delaysigma"]
        self.dsA.periods = period
        self.dsA.delays = delay
        self.dsA.eating[0] = False
        self.dsA.times[0] = 0.0
        self.dsA.statechanges = period * np.random.random(N)
        
        Mesenchymal.classInit(self.const)
        for agentIndex in range(N_mesenchymal+N_amoeboid):
            tryToPlace = True
            nAttempts = 0
            while tryToPlace:
                initX = np.random.normal(initial_position[0], stray)
                initY = np.random.normal(initial_position[1], stray)
                posidx = np.array(density * np.array([initX, initY]), dtype=np.int0)
                np.clip(posidx, myMaze.minidx, myMaze.maxidx, out=posidx)
                onECM = (maze[posidx[0],posidx[1]] > 0.5 * constants.wallconst)
                if not onECM:
                    self.dsA.positions[0,agentIndex] = np.array([initX, initY])
                    tryToPlace = False
                else:
                    nAttempts += 1
                    assert nAttempts < 15, "Could not place agents outside of ECM for given parameters"
        
        posidx = np.array(density * self.dsA.positions[0], dtype=np.int0)
        
        x = np.array(cgrad[0,posidx[:,0],posidx[:,1]])
        y = np.array(cgrad[1,posidx[:,0],posidx[:,1]])
        self.dsA.direction_angles = np.arctan2(y, x)
        self.dsA.direction_angles[isMesenchymal] += self.const["compass_noise_m"] * np.random.standard_normal(N_mesenchymal)
        self.dsA.direction_angles[isAmoeboid] += self.const["compass_noise_a"] * np.random.standard_normal(N_amoeboid)
        
        if isMesenchymal.any():
            assert Mesenchymal.getMaxEatingDistance(density)<=myMaze.border, "The area where Mesenchymal eat is too large compared to the border of the maze"
        
        #how often do we want to update the user about the progress (period)
        update_progress = 50
        do_continue = True
        max_time = self.const["max_time"]
        lasttime = dt
        simtime = dt
        margin = self.const["border"]
        fieldlimits = self.const["fieldlimits"]
        iii = 1
        enable_interaction = self.const["enable_interaction"]
        #notDiag = ~np.eye(N, dtype=np.bool_)
        r_coupling = self.const["repulsion_coupling"]
        w = self.const["w"] * dt
        _w = (1-w) * dt
        interaction_radius = self.const["interaction_radius"]
        alignment_radius = self.const["alignment_radius"]
        q = self.const["q"]
        eta = self.const["eta"]
        gamma_a = self.const["gamma_a"]
        gamma_m = self.const["gamma_m"]
        r = self.const["r"]
        one_over_m = 1/self.const["mass"]
        #success_radius = self.const["success_radius"]
        success_radius_sq = self.const["success_radius"]**2
        delta = self.const["delta"]
        compass_noise_a = self.const["compass_noise_a"]
        compass_noise_m = self.const["compass_noise_m"]
        directions = np.zeros((N, DIM))
        directions[:,0] = np.cos(self.dsA.direction_angles)
        directions[:,1] = np.sin(self.dsA.direction_angles)
        degradation = np.zeros(N)
        degradation_radius = self.const["degradation_radius"]
        nodegradationlimit = self.const["nodegradationlimit"]
        
        positions = self.dsA.positions
        velocities = self.dsA.velocities
        energies = self.dsA.energies
        states = self.dsA.states
        statechanges = self.dsA.statechanges
        eating = self.dsA.eating
        periods = self.dsA.periods
        delays = self.dsA.delays
        times = self.dsA.times
        direction_angles = self.dsA.direction_angles
        has_had_update = np.zeros(direction_angles.shape, dtype=np.int_)
        
        dragFactor = np.empty((N,))
        F_repulsion = np.zeros((N,2))
        
        lastPositions = np.array(positions[0])
        lastVelocities = np.array(velocities[0])
        currentPositions = np.array(positions[0])
        currentVelocities = np.array(velocities[0])

        while do_continue:
            if simtime-lasttime>update_progress:
                info("Time %0.2f out of maximum %s" % (simtime,max_time))
                lasttime = simtime
            
            states[iii] = states[iii-1]     
            E = energies[iii-1]
            times[iii] = simtime
            
            #Create custom variables for the last timestemp's values of positions[] and velocities[] arrays.
            #This is done because positions and velocities are memmaps which are slower in handling.
            lastPositions = currentPositions
            lastVelocities = currentVelocities

            F_repulsion[:] = 0.0
            if enable_interaction:
                #calculate distances between agents
                #we create an array containing in N times the array containing the agents' positions
                #and we substract from that array its transpose (of some sort)
                pos_v = np.repeat([lastPositions], N, axis=0)
                pos_h = pos_v.swapaxes(0,1)
                pos_difference = pos_v-pos_h
                d_squared = np.sum(pos_difference*pos_difference, axis=2)
                
                inRepulsionRadius = d_squared < 4*interaction_radius*interaction_radius
                #do not let agents interact with themselves (i.e. the diagonal has to be False)
                np.fill_diagonal(inRepulsionRadius, False)
                inAlignmentRadius = d_squared < 4*alignment_radius*alignment_radius
                #do not let agents interact with themselves (i.e. the diagonal has to be False)
                np.fill_diagonal(inAlignmentRadius, False)
                doRepulse = inRepulsionRadius
                doAlign = np.logical_and(~inRepulsionRadius, inAlignmentRadius) #@UnusedVariable
                if useWeave:
                    code = """
                    #line 186 "classSimulation.py"
                    int nInteract;
                    double meanX, meanY;
                    for (int i=0; i < N; i++) {
                        nInteract = 0;
                        meanX = 0.0;
                        meanY = 0.0;
                        for (int j=0; j < N; j++) {
                            if (DOALIGN2(i, j) == 1) {
                                nInteract++;
                                meanX += DIRECTIONS2(j,0);
                                meanY += DIRECTIONS2(j,1);
                            }
                        }
                        if (nInteract != 0) {
                            meanX /= nInteract;
                            meanY /= nInteract;
                            DIRECTIONS2(i,0) = _w*DIRECTIONS2(i,0) + w*meanX;
                            DIRECTIONS2(i,1) = _w*DIRECTIONS2(i,1) + w*meanY;
                        }        
                    }
                    """
                    #weave.inline(code, ["N", "doAlign", "directions", "_w", "w"], type_converters=converters.blitz)
                    weave.inline(code, ["N", "doAlign", "directions", "_w", "w"])
                else:
                    for i in xrange(N):
                        if doAlign[i].any():
                            means = np.mean( directions[doAlign[i]], axis=0)
                            directions[i] = _w*directions[i] + w*means
                dir_norms = np.sqrt( directions[:,0]*directions[:,0] + directions[:,1]*directions[:,1] )
                dir_norms[dir_norms==0.0] = 1.0
                directions = directions/dir_norms[:, np.newaxis]
                #directions[:,0] = directions[:,0]/dir_norms
                #directions[:,1] = directions[:,1]/dir_norms

                F_rep = np.zeros_like(pos_difference)
                interactionIndices = np.nonzero(doRepulse)
                for i, j in zip(interactionIndices[0], interactionIndices[1]):
                    F_rep[i,j] = r_coupling * pos_difference[i,j,:] / d_squared[i,j,np.newaxis]
                F_repulsion = np.sum(F_rep, axis=0)

            posidx = np.array(density * lastPositions, dtype=np.int0)
            np.clip(posidx, myMaze.minidx, myMaze.maxidx, out=posidx)
            wgrad = myMaze.getGradients(posidx)

            evolve_orientation = statechanges < simtime 
            is_moving = states[iii-1]==sim.States.MOVING
            is_orienting = states[iii-1]==sim.States.ORIENTING
            theta = np.zeros(self.N)
            theta[is_moving] = 1.0
            
            switch_to_orienting = np.logical_and(evolve_orientation, is_moving)
            if switch_to_orienting.any():
                states[iii][switch_to_orienting] = sim.States.ORIENTING
                statechanges[switch_to_orienting] = simtime + delays[switch_to_orienting]

            switch_to_moving = np.logical_and(evolve_orientation, is_orienting)
            if switch_to_moving.any():
                states[iii][switch_to_moving] = sim.States.MOVING
                statechanges[switch_to_moving] = simtime + periods[switch_to_moving]
                x = np.array(cgrad[0,posidx[switch_to_moving,0],posidx[switch_to_moving,1]])
                y = np.array(cgrad[1,posidx[switch_to_moving,0],posidx[switch_to_moving,1]])
                direction_angles[switch_to_moving] = np.arctan2(y, x)
                switch_to_moving_a = np.logical_and(switch_to_moving, isAmoeboid)
                switch_to_moving_m = np.logical_and(switch_to_moving, isMesenchymal)
                direction_angles[switch_to_moving_a] += compass_noise_a * np.random.standard_normal(np.count_nonzero(switch_to_moving_a))
                direction_angles[switch_to_moving_m] += compass_noise_m * np.random.standard_normal(np.count_nonzero(switch_to_moving_m))
                
                directions[switch_to_moving, 0] = np.cos(direction_angles[switch_to_moving])
                directions[switch_to_moving, 1] = np.sin(direction_angles[switch_to_moving])
            
            propelFactor = eta * E * theta
            F_propulsion = propelFactor[:,np.newaxis] * directions
             
            dragFactor[isAmoeboid] = - gamma_a
            dragFactor[isMesenchymal] = - gamma_m
            
            F_drag = dragFactor[:,np.newaxis] * lastVelocities
            
            F_stoch = r * np.random.standard_normal(size=F_propulsion.shape)
            
            F_total = F_propulsion + F_drag + F_stoch + F_repulsion
            
            #Check if new position is allowed, otherwise move back 
            ta = lastPositions[:,0]<fieldlimits[0]+margin
            tb = lastPositions[:,0]>fieldlimits[1]-margin
            tc = lastPositions[:,1]<fieldlimits[2]+margin
            td = lastPositions[:,1]>fieldlimits[3]-margin
            outsidePlayingField = np.logical_or(ta, tb)
            outsidePlayingField = np.logical_or(outsidePlayingField, tc)
            outsidePlayingField = np.logical_or(outsidePlayingField, td)
            
            nda = lastPositions[:,0]<fieldlimits[0]+nodegradationlimit
            ndb = lastPositions[:,0]>fieldlimits[1]-nodegradationlimit
            ndc = lastPositions[:,1]<fieldlimits[2]+nodegradationlimit
            ndd = lastPositions[:,1]>fieldlimits[3]-nodegradationlimit
            noDegradation = np.logical_or(nda, ndb)
            noDegradation = np.logical_or(noDegradation, ndc)
            noDegradation = np.logical_or(noDegradation, ndd)            
            
            wallnorm = np.sum(wgrad * wgrad, axis=1)
            touchingECM = (wallnorm != 0.0)

            collidingWithWall = np.logical_and(touchingECM, isAmoeboid)
            collidingWithWall = np.logical_or(collidingWithWall, outsidePlayingField)
            collidingWithWall = np.logical_or(collidingWithWall, np.logical_and(isMesenchymal, noDegradation))

            if collidingWithWall.any():
                dotF = np.zeros((self.N))
                dotF[collidingWithWall] = np.sum(F_total[collidingWithWall] * wgrad[collidingWithWall], axis=1)
                doAdjust = dotF<0
                if doAdjust.any():
                    dotF[doAdjust] /= wallnorm[doAdjust]
                    F_total[doAdjust] -=  dotF[doAdjust][:,np.newaxis] * wgrad[doAdjust]

            currentVelocities = lastVelocities + one_over_m * dt * F_total
            
            if collidingWithWall.any():
                dotv = np.zeros((self.N))
                dotv[collidingWithWall] = np.sum(currentVelocities[collidingWithWall] * wgrad[collidingWithWall], axis=1)
                doAdjust = dotv<0
                if doAdjust.any():
                    dotv[doAdjust] /= wallnorm[doAdjust]
                    currentVelocities[doAdjust] -= dotv[doAdjust][:,np.newaxis] * wgrad[doAdjust]

            currentPositions = lastPositions + currentVelocities * dt
            
            #TODO: next line don't let the ones outside the playing field degrade
            posidx = np.array(density * lastPositions, dtype=np.int0)
            np.clip(posidx, myMaze.minidx, myMaze.maxidx, out=posidx)
            ECM = maze[posidx[:,0],posidx[:,1]]
            #TODO remove hardcoded value here
            inOriginalECM = ECM > 0.7 * constants.wallconst
            inContactWithECM = np.logical_or(touchingECM, inOriginalECM)
            isDegrading = np.logical_and(isMesenchymal, inContactWithECM)
            isDegrading = np.logical_and(isDegrading, ~noDegradation)

            #if an agent is degrading now then he should be degrading during the next 'degrading_bias' steps
            vel = currentVelocities
            v = np.sqrt(np.sum(vel*vel, axis=1))

            for i in isDegrading.nonzero()[0]:
                #degradation_radius has to be in distance units, not pixels!
                bias = int(degradation_radius/(v[i]*dt * density[0] )) if v[i] > 0 else 0
                nextIdx = min(NNN, iii+bias)
                eating[iii:nextIdx, i] = True
            
            kappa = np.logical_or(isDegrading, eating[iii])
            
            for pos, energy in zip(currentPositions[eating[iii]], E[eating[iii]]):
                myMaze.degrade(pos, Mesenchymal.eat, energy, density, dt)
            
            needs_update = isDegrading
            has_had_update[needs_update] = iii

            degradation[:] = 0.0
            degradation[kappa] = Mesenchymal.degrad_rate
            
            energies[iii] = E + (q - delta * E - theta * eta * v * E - degradation * E) * dt
            energies[iii][ energies[iii]<0.0 ] = 0.0
            
            distances_sq = statutils.getDistancesSq(currentPositions, goal)
            states[iii][distances_sq < success_radius_sq] = sim.States.CLOSE
            
            #Save positions and velocities in arrays that are going to be written to disk later
            positions[iii] = currentPositions
            velocities[iii] = currentVelocities
            
            simtime += dt
            iii += 1
            do_continue = iii<NNN

        self.iii = iii-1
        self.simtime = simtime
        t_stop = datetime.datetime.now()
        info( "Simulation ended ")
        info( "Simulation took %s and ended with a simulation time of %s" % (t_stop-t_start, simtime))
        
        if self.dsA is not None:
            if self.retainCompleteDataset:
                self.dsA.resizeTo(iii)
                self.dsA.saveTo(self.resultsdir)
                #save the maze of the last time step so we can reuse it for the path plots
                with open(os.path.join(self.resultsdir, constants.finalmaze_filename), "w") as finalmaze:
                    np.save(finalmaze, myMaze.data)
            else:
                self.dsA.erase()
        
        saved_constants = utils.getResultsFilepath(constants.resultspath, self.const["name"], constants.saved_constants_filename)
        statutils.saveConst(self.const, saved_constants)
               
        utils.savetimestamp(self.resultsdir)
        utils.remove_logging_sim(logging_handler)
    
    def saveFinalGradient(self, myMaze):
        """Use this if you're interested in an image of what the maze looks like at the end of the simulation."""
        import Image
        imgdata = myMaze.getGradImageSquared()
        imgdata = utils.scaleToMax(255.0, imgdata.T)
        imgdata = np.flipud(imgdata)
        img = Image.fromarray(imgdata.astype('uint8'))
        img.save(os.path.join(self.resultsdir, "lastGradient.bmp"))
    
    def reportLastMazeGrad(self, steps, iii, idxA, positions, density, mazegrad, times, number):
        import plotting
        bk = steps
        line = positions[iii-bk:iii, idxA]
        posidx = np.array(density * line, dtype=np.int_)
        mazepoints = mazegrad[:,posidx[:,0],posidx[:,1]]
        mazepoints = np.sqrt(mazepoints[0]*mazepoints[0] + mazepoints[1]*mazepoints[1])
        y = [mazepoints]
        plotting.plot([range(len(mazepoints))] , y, folder=self.resultsdir, savefile="mazeline_%d.png" % number)
    
    def analyse(self):
        """Saves the ``finalstats`` a pickle file and a text file in the results folder."""
        picklepath = utils.getResultsFilepath(self.resultsdir, constants.finalstats_pickle)
        textpath = utils.getResultsFilepath(self.resultsdir, constants.finalstats_text)
        statutils.savefinalstats(picklepath, textpath, self.const, self.dsA)
    
    def cleanUp(self):
        """Cleans up the simulation and removes its directory. Should only be used if something went wrong."""
        if self.dsA is not None:
            self.dsA.erase()
        shutil.rmtree(self.resultsdir)
        utils.info("Cleaned up results directory.")

def prepareSim(const):
    """Sets up a single simulation to be run directly (i.e., without resorting to :py:mod: main.py)."""
    utils.setup_logging_base() 
    #run the simulation
    mySim = Simulation(const)
    mySim.run()
    #run analysis algorithms
    mySim.analyse()
    functions = []
    import graphics
    if const["create_video_directly"]:
        functions.append(graphics.create_video)
    if const["create_path_plot"]:
        functions.append(graphics.create_path_plot)
    graphics.writeFrames(const, output_func=functions)
    
if __name__ == "__main__":
    """Runs a single simulation without going via :py:mod main.py."""
    simfile = constants.currentsim
    #TODO: should add unravel here
    const = utils.readConst(constants.simdir, simfile)
    const = const["get"](tuple())
    prepareSim(const)