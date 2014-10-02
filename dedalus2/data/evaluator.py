"""
Class for centralized evaluation of expression trees.

"""

import os
from collections import defaultdict
import pathlib
import h5py
import numpy as np
from mpi4py import MPI

from .system import FieldSystem
from .operators import Operator, Cast
from ..tools.array import reshape_vector
from ..tools.general import OrderedSet
from ..tools.parallel import Sync


class Evaluator:
    """
    Coordinates evaluation of operator trees through various handlers.

    Parameters
    ----------
    domain : domain object
        Problem domain
    vars : dict
        Variables for parsing task expression strings

    """

    def __init__(self, domain, vars):

        self.domain = domain
        self.vars = vars
        self.handlers = []
        self.groups = defaultdict(list)

    def add_dictionary_handler(self, **kw):
        """Create a dictionary handler and add to evaluator."""

        DH = DictionaryHandler(self.domain, self.vars, **kw)
        return self.add_handler(DH)

    def add_system_handler(self, **kw):
        """Create a system handler and add to evaluator."""

        SH = SystemHandler(self.domain, self.vars, **kw)
        return self.add_handler(SH)

    def add_file_handler(self, filename, **kw):
        """Create a file handler and add to evaluator."""

        FH = FileHandler(filename, self.domain, self.vars, **kw)
        return self.add_handler(FH)

    def add_handler(self, handler):
        """Add a handler to evaluator."""

        self.handlers.append(handler)
        # Register with group
        if handler.group is not None:
            self.groups[handler.group].append(handler)
        return handler

    def evaluate_group(self, group, wall_time, sim_time, iteration):
        """Evaluate all handlers in a group."""

        handlers = self.groups[group]
        self.evaluate_handlers(handlers, wall_time, sim_time, iteration)

    def evaluate_scheduled(self, wall_time, sim_time, iteration):
        """Evaluate all scheduled handlers."""

        scheduled_handlers = []
        for handler in self.handlers:
            # Get cadence devisors
            wall_div = wall_time // handler.wall_dt
            sim_div  = sim_time  // handler.sim_dt
            iter_div = iteration // handler.iter
            # Compare to divisor at last evaluation
            wall_up = (wall_div > handler.last_wall_div)
            sim_up  = (sim_div  > handler.last_sim_div)
            iter_up = (iter_div > handler.last_iter_div)

            if any((wall_up, sim_up, iter_up)):
                scheduled_handlers.append(handler)
                # Update all divisors
                handler.last_wall_div = wall_div
                handler.last_sim_div  = sim_div
                handler.last_iter_div = iter_div

        self.evaluate_handlers(scheduled_handlers, wall_time, sim_time, iteration)

    def evaluate_handlers(self, handlers, wall_time, sim_time, iteration):
        """Evaluate a collection of handlers."""

        # Attempt tasks in current layout
        tasks = [t for h in handlers for t in h.tasks]
        tasks = self.attempt_tasks(tasks, id=sim_time)

        # Move all to coefficient layout
        fields = self.get_fields(tasks)
        for f in fields:
            f.require_coeff_space()
        tasks = self.attempt_tasks(tasks, id=sim_time)

        # Oscillate through layouts until all tasks are evaluated
        L = 0
        Lmax = self.domain.distributor.grid_layout.index
        while tasks:
            # Change direction at first and last layouts
            if L == 0:
                dL = 1
            elif L == Lmax:
                dL = -1
            # Transform fields
            fields = self.get_fields(tasks)
            for f in fields:
                if dL > 0:
                    f.towards_grid_space()
                else:
                    f.towards_coeff_space()
            L += dL
            # Attempt evaluation
            tasks = self.attempt_tasks(tasks, id=sim_time)

        # Transform all outputs to coefficient layout to dealias
        for handler in handlers:
            for task in handler.tasks:
                task['out'].require_coeff_space()

        # Process
        for handler in handlers:
            handler.process(wall_time, sim_time, iteration)

    @staticmethod
    def get_fields(tasks):
        """Get field set for a collection of tasks."""

        fields = OrderedSet()
        for task in tasks:
            fields.update(task['operator'].field_set())

        return fields

    @staticmethod
    def attempt_tasks(tasks, **kw):
        """Attempt tasks and return the unfinished ones."""

        unfinished = []
        for task in tasks:
            output = task['operator'].attempt(**kw)
            if output is None:
                unfinished.append(task)
            else:
                task['out'] = output

        return unfinished


class Handler:
    """
    Group of tasks with associated scheduling data.

    Parameters
    ----------
    domain : domain object
        Problem domain
    vars : dict
        Variables for parsing task expression strings
    group : str, optional
        Group name for forcing selected handelrs (default: None)
    wall_dt : float, optional
        Wall time cadence for evaluating tasks (default: infinite)
    sim_dt : float, optional
        Simulation time cadence for evaluating tasks (default: infinite)
    iter : int, optional
        Iteration cadence for evaluating tasks (default: infinite)

    """

    def __init__(self, domain, vars, group=None, wall_dt=np.inf, sim_dt=np.inf, iter=np.inf):

        # Attributes
        self.domain = domain
        self.vars = vars
        self.group = group
        self.wall_dt = wall_dt
        self.sim_dt = sim_dt
        self.iter = iter

        self.tasks = []
        # Set initial divisors to be scheduled for sim_time, iteration = 0
        self.last_wall_div = -1
        self.last_sim_div = -1
        self.last_iter_div = -1

    def add_task(self, task, layout='g', name=None):
        """Add task to handler."""

        # Default name
        if name is None:
            name = str(task)

        # Create operator
        if isinstance(task, Operator):
            op = task
        elif isinstance(task, str):
            op = Operator.from_string(task, self.vars, self.domain)
        else:
            op = Cast(task)

        # Build task dictionary
        task = dict()
        task['operator'] = op
        task['layout'] = self.domain.distributor.get_layout_object(layout)
        task['name'] = name

        self.tasks.append(task)

    def add_tasks(self, tasks, **kw):
        """Add multiple tasks."""

        name = kw.pop('name', '')
        for task in tasks:
            tname = name + str(task)
            self.add_task(task, name=tname, **kw)

    def add_system(self, system, **kw):
        """Add fields from a FieldSystem."""

        self.add_tasks(system.fields, **kw)


class DictionaryHandler(Handler):
    """Handler that stores outputs in a dictionary."""

    def __init__(self, *args, **kw):

        Handler.__init__(self, *args, **kw)
        self.fields = dict()

    def process(self, wall_time, sim_time, iteration):
        """Reference fields from dictionary."""

        for task in self.tasks:
            task['out'].require_layout(task['layout'])
            self.fields[task['name']] = task['out']


class SystemHandler(Handler):
    """Handler that sets fields in a FieldSystem."""

    def build_system(self):
        """Build FieldSystem and set task outputs."""

        nfields = len(self.tasks)
        self.system = FieldSystem(range(nfields), self.domain)

        for i, task in enumerate(self.tasks):
            task['operator'].out = self.system.fields[i]

        return self.system

    def process(self, wall_time, sim_time, iteration):
        """Gather fields into system."""

        self.system.gather()


class FileHandler(Handler):
    """
    Handler that writes tasks to an HDF5 file.

    Parameters
    ----------
    filename : str
        Base of filename, without an extension
    max_writes : int, optional
        Maximum number of writes to a single file (default: infinite)
    max_size : int, optional
        Maximum file size to write to, in bytes (default: 2**30 = 1 GB).
        (Note: files may be larger after final write.)

    """

    def __init__(self, base_path, *args, max_writes=np.inf, max_size=2**30, parallel=False, **kw):

        Handler.__init__(self, *args, **kw)

        # Check base_path
        base_path = pathlib.Path(base_path).absolute()
        if any(base_path.suffixes):
            raise ValueError("base_path should indicate a folder for storing HDF5 files.")
        if not base_path.exists():
            with Sync(self.domain.distributor.comm_cart):
                if self.domain.distributor.rank == 0:
                    base_path.mkdir()

        # Attributes
        self.base_path = base_path
        self.max_writes = max_writes
        self.max_size = max_size
        self.parallel = parallel
        self._sl_array = np.zeros(1, dtype=int)

        self.file_num = 0
        self.current_path = None
        self.total_write_num = 0
        self.file_write_num = 0

        if parallel:
            # Set HDF5 property list for collective writing
            self._property_list = h5py.h5p.create(h5py.h5p.DATASET_XFER)
            self._property_list.set_dxpl_mpio(h5py.h5fd.MPIO_COLLECTIVE)

    def check_file_limits(self):
        """Check if write or size limits have been reached."""

        write_limit = ((self.total_write_num % self.max_writes) == 0)
        size_limit = (self.current_path.stat().st_size >= self.max_size)
        if not self.parallel:
            # reduce(size_limit, or) across processes
            comm = self.domain.distributor.comm_cart
            self._sl_array[0] = size_limit
            comm.Allreduce(MPI.IN_PLACE, self._sl_array, op=MPI.LOR)
            size_limit = self._sl_array[0]

        return (write_limit or size_limit)

    def get_file(self):
        """Return current HDF5 file, creating if necessary."""
        # Create file on first call
        if not self.current_path:
            return self.new_file()
        # Create file at file limits
        if self.check_file_limits():
            return self.new_file()
        # Otherwise open current file
        if self.parallel:
            comm = self.domain.distributor.comm_cart
            return h5py.File(str(self.current_path), 'a', driver='mpio', comm=comm)
        else:
            return h5py.File(str(self.current_path), 'a')

    def new_file(self):
        """Generate new HDF5 file."""

        domain = self.domain

        # Create next file
        self.file_num += 1
        self.file_write_num = 0
        comm = domain.distributor.comm_cart
        if self.parallel:
            # Save in base directory
            file_name = '%s_f%i.hdf5' %(self.base_path.stem, self.file_num)
            self.current_path = self.base_path.joinpath(file_name)
            file = h5py.File(str(self.current_path), 'w', driver='mpio', comm=comm)
        else:
            # Save in folders for each filenum in base directory
            folder_name = '%s_f%i' %(self.base_path.stem, self.file_num)
            folder_path = self.base_path.joinpath(folder_name)
            if not folder_path.exists():
                with Sync(domain.distributor.comm_cart):
                    if domain.distributor.rank == 0:
                        folder_path.mkdir()
            file_name = '%s_f%i_p%i.h5' %(self.base_path.stem, self.file_num, comm.rank)
            self.current_path = folder_path.joinpath(file_name)
            file = h5py.File(str(self.current_path), 'w')

        self.setup_file(file)

        return file

    def setup_file(self, file):

        domain = self.domain

        # Metadeta
        file.attrs['file_number'] = self.file_num
        file.attrs['handler_name'] = self.base_path.stem
        file.attrs['writes'] = self.file_write_num
        if not self.parallel:
            file.attrs['mpi_rank'] = domain.distributor.comm_cart.rank
            file.attrs['mpi_size'] = domain.distributor.comm_cart.size

        # Scales
        scale_group = file.create_group('scales')
        # Start time scales with shape=(0,) to chunk across writes
        scale_group.create_dataset(name='sim_time', shape=(0,), maxshape=(None,), dtype=np.float64)
        scale_group.create_dataset(name='wall_time', shape=(0,), maxshape=(None,), dtype=np.float64)
        scale_group.create_dataset(name='iteration', shape=(0,), maxshape=(None,), dtype=np.int)
        scale_group.create_dataset(name='write_number', shape=(0,), maxshape=(None,), dtype=np.int)
        const = scale_group.create_dataset(name='constant', data=np.array([0.], dtype=np.float64))
        for axis, basis in enumerate(domain.bases):
            grid = basis.grid
            elem = basis.elements
            gdset = scale_group.create_dataset(name=basis.name, shape=grid.shape, dtype=grid.dtype)
            edset = scale_group.create_dataset(name=basis.element_label+basis.name, shape=elem.shape, dtype=elem.dtype)
            if (not self.parallel) or (domain.distributor.rank == 0):
                gdset[:] = grid
                edset[:] = elem

        # Tasks
        task_group =  file.create_group('tasks')
        for task_num, task in enumerate(self.tasks):
            layout = task['layout']
            constant = task['operator'].constant
            gnc_shape, gnc_start, write_shape, write_start, write_count = self.get_write_stats(layout, constant, index=0)
            if np.prod(write_shape) <= 1:
                # Start with shape[0] = 0 to chunk across writes for scalars
                file_shape = (0,) + tuple(write_shape)
            else:
                # Start with shape[0] = 1 to chunk within writes
                file_shape = (1,) + tuple(write_shape)
            file_max = (None,) + tuple(write_shape)
            dset = task_group.create_dataset(name=task['name'], shape=file_shape, maxshape=file_max, dtype=layout.dtype)
            if not self.parallel:
                dset.attrs['global_shape'] = gnc_shape
                dset.attrs['start'] = gnc_start
                dset.attrs['count'] = write_count

            # Metadata and scales
            dset.attrs['task_number'] = task_num
            dset.attrs['constant'] = constant
            dset.attrs['grid_space'] = layout.grid_space

            # Time scales
            dset.dims[0].label = 't'
            for sn in ['sim_time', 'wall_time', 'iteration', 'write_number']:
                scale = scale_group[sn]
                dset.dims.create_scale(scale, sn)
                dset.dims[0].attach_scale(scale)

            # Spatial scales
            for axis, basis in enumerate(domain.bases):
                if constant[axis]:
                    sn = 'constant'
                else:
                    if layout.grid_space[axis]:
                        sn = basis.name
                    else:
                        sn = basis.element_label + basis.name
                scale = scale_group[sn]
                dset.dims.create_scale(scale, sn)
                dset.dims[axis+1].label = sn
                dset.dims[axis+1].attach_scale(scale)

    def process(self, wall_time, sim_time, iteration):
        """Save task outputs to HDF5 file."""

        file = self.get_file()
        self.total_write_num += 1
        self.file_write_num += 1
        file.attrs['writes'] = self.file_write_num
        index = self.file_write_num - 1

        # Update time scales
        sim_time_dset = file['scales/sim_time']
        wall_time_dset = file['scales/wall_time']
        iteration_dset = file['scales/iteration']
        write_num_dset = file['scales/write_number']

        sim_time_dset.resize(index+1, axis=0)
        sim_time_dset[index] = sim_time
        wall_time_dset.resize(index+1, axis=0)
        wall_time_dset[index] = wall_time
        iteration_dset.resize(index+1, axis=0)
        iteration_dset[index] = iteration
        write_num_dset.resize(index+1, axis=0)
        write_num_dset[index] = self.total_write_num

        # Create task datasets
        for task_num, task in enumerate(self.tasks):
            out = task['out']
            out.require_layout(task['layout'])

            dset = file['tasks'][task['name']]
            dset.resize(index+1, axis=0)

            memory_space, file_space = self.get_hdf5_spaces(out.layout, out.constant, index)
            if self.parallel:
                dset.id.write(memory_space, file_space, out.data, dxpl=self._property_list)
            else:
                dset.id.write(memory_space, file_space, out.data)

        file.close()

    def get_write_stats(self, layout, constant, index):
        """Determine write parameters for nonconstant subspace of a field."""

        # References
        gshape = layout.global_shape
        lshape = layout.shape
        start = layout.start
        first = (start == 0)

        # Build counts, taking just the first entry along constant axes
        write_count = lshape.copy()
        write_count[constant & first] = 1
        write_count[constant & ~first] = 0

        # Collectively writing global data
        global_nc_shape = gshape.copy()
        global_nc_shape[constant] = 1
        global_nc_start = start.copy()
        global_nc_start[constant & ~first] = 1

        if self.parallel:
            # Collectively writing global data
            write_shape = global_nc_shape
            write_start = global_nc_start
        else:
            # Independently writing local data
            write_shape = write_count
            write_start = 0 * start

        return global_nc_shape, global_nc_start, write_shape, write_start, write_count

    def get_hdf5_spaces(self, layout, constant, index):
        """Create HDF5 space objects for writing nonconstant subspace of a field."""

        # References
        lshape = layout.shape
        start = layout.start
        gnc_shape, gnc_start, write_shape, write_start, write_count = self.get_write_stats(layout, constant, index)

        # Build HDF5 spaces
        memory_shape = tuple(lshape)
        memory_start = tuple(0 * start)
        memory_count = tuple(write_count)
        memory_space = h5py.h5s.create_simple(memory_shape)
        memory_space.select_hyperslab(memory_start, memory_count)

        file_shape = (index+1,) + tuple(write_shape)
        file_start = (index,) + tuple(write_start)
        file_count = (1,) + tuple(write_count)
        file_space = h5py.h5s.create_simple(file_shape)
        file_space.select_hyperslab(file_start, file_count)

        return memory_space, file_space
