import meep as mp
try:
    import meep.adjoint as mpa
except:
    import adjoint as mpa
import numpy as np
from autograd import numpy as npa
from autograd import tensor_jacobian_product
import unittest
from enum import Enum
from utils import VectorComparisonMixin

MonitorObject = Enum('MonitorObject', 'EIGENMODE DFT')

resolution = 25

silicon = mp.Medium(epsilon=12)

sxy = 5.0
cell_size = mp.Vector3(sxy,sxy,0)

dpml = 1.0
boundary_layers = [mp.PML(thickness=dpml)]

eig_parity = mp.EVEN_Y + mp.ODD_Z

design_shape = mp.Vector3(1.5,1.5)
design_region_resolution = int(2*resolution)
Nx = int(design_region_resolution*design_shape.x)
Ny = int(design_region_resolution*design_shape.y)

## ensure reproducible results
np.random.seed(9861548)

## random design region
p = np.random.rand(Nx*Ny)

## random epsilon perturbation for design region
deps = 1e-5
dp = deps*np.random.rand(Nx*Ny)

w = 1.0
waveguide_geometry = [mp.Block(material=silicon,
                               center=mp.Vector3(),
                               size=mp.Vector3(mp.inf,w,mp.inf))]

fcen = 1/1.55
df = 0.23*fcen
sources = [mp.EigenModeSource(src=mp.GaussianSource(fcen,fwidth=df),
                              center=mp.Vector3(-0.5*sxy+dpml,0),
                              size=mp.Vector3(0,sxy),
                              eig_band=1,
                              eig_parity=eig_parity)]


def forward_simulation(design_params,mon_type,frequencies=None):
    matgrid = mp.MaterialGrid(mp.Vector3(Nx,Ny),
                              mp.air,
                              silicon,
                              weights=design_params.reshape(Nx,Ny),
                              grid_type='U_MEAN')
            
    matgrid_geometry = [mp.Block(center=mp.Vector3(),
                                 size=mp.Vector3(design_shape.x,design_shape.y,0),
                                 material=matgrid)]

    geometry = waveguide_geometry + matgrid_geometry

    sim = mp.Simulation(resolution=resolution,
                        cell_size=cell_size,
                        boundary_layers=boundary_layers,
                        sources=sources,
                        geometry=geometry)
    if not frequencies:
        frequencies = [fcen]

    if mon_type.name == 'EIGENMODE':
        mode = sim.add_mode_monitor(frequencies,
                                    mp.ModeRegion(center=mp.Vector3(0.5*sxy-dpml),size=mp.Vector3(0,sxy,0)),
                                    yee_grid=True)

    elif mon_type.name == 'DFT':
        mode = sim.add_dft_fields([mp.Ez],
                                  frequencies,
                                  center=mp.Vector3(1.25),
                                  size=mp.Vector3(0.25,1,0),
                                  yee_grid=False)

    sim.run(until_after_sources=50)

    if mon_type.name == 'EIGENMODE':
        coeff = sim.get_eigenmode_coefficients(mode,[1],eig_parity).alpha[0,:,0]
        S12 = abs(coeff)**2

    elif mon_type.name == 'DFT':
        Ez2 = []
        for f in range(len(frequencies)):
            Ez_dft = sim.get_dft_array(mode, mp.Ez, f)
            Ez2.append(abs(Ez_dft[4,10])**2)
        Ez2 = np.array(Ez2)

    sim.reset_meep()

    if mon_type.name == 'EIGENMODE':
        return S12
    elif mon_type.name == 'DFT':
        return Ez2


def adjoint_solver(design_params, mon_type, frequencies=None):
    matgrid = mp.MaterialGrid(mp.Vector3(Nx,Ny),
                              mp.air,
                              silicon,
                              weights=np.ones((Nx,Ny)))

    matgrid_region = mpa.DesignRegion(matgrid,
                                      volume=mp.Volume(center=mp.Vector3(),
                                                       size=mp.Vector3(design_shape.x,design_shape.y,0)))

    matgrid_geometry = [mp.Block(center=matgrid_region.center,
                                 size=matgrid_region.size,
                                 material=matgrid)]

    geometry = waveguide_geometry + matgrid_geometry

    sim = mp.Simulation(resolution=resolution,
                        cell_size=cell_size,
                        boundary_layers=boundary_layers,
                        sources=sources,
                        geometry=geometry)
    if not frequencies:
        frequencies = [fcen]

    if mon_type.name == 'EIGENMODE':
        obj_list = [mpa.EigenmodeCoefficient(sim,
                                             mp.Volume(center=mp.Vector3(0.5*sxy-dpml),
                                                       size=mp.Vector3(0,sxy,0)),1)]

        def J(mode_mon):
            return npa.abs(mode_mon)**2

    elif mon_type.name == 'DFT':
        obj_list = [mpa.FourierFields(sim,
                                      mp.Volume(center=mp.Vector3(1.25),
                                                size=mp.Vector3(0.25,1,0)),
                                      mp.Ez)]

        def J(mode_mon):
            return npa.abs(mode_mon[:,4,10])**2

    opt = mpa.OptimizationProblem(
        simulation = sim,
        objective_functions = J,
        objective_arguments = obj_list,
        design_regions = [matgrid_region],
        frequencies=frequencies,
        decay_fields=[mp.Ez])

    f, dJ_du = opt([design_params])

    sim.reset_meep()

    return f, dJ_du


def mapping(x,filter_radius,eta,beta):
    filtered_field = mpa.conic_filter(x,filter_radius,design_shape.x,design_shape.y,design_region_resolution)

    projected_field = mpa.tanh_projection(filtered_field,beta,eta)

    return projected_field.flatten()


class TestAdjointSolver(VectorComparisonMixin, unittest.TestCase):

    def test_adjoint_solver_DFT_fields(self):
        print("*** TESTING DFT ADJOINT FEATURES ***")
        ## test the single frequency and multi frequency cases
        for frequencies in [[fcen], [1/1.58, fcen, 1/1.53]]:
            ## compute gradient using adjoint solver
            adjsol_obj, adjsol_grad = adjoint_solver(p, MonitorObject.DFT, frequencies)

            ## compute unperturbed S12
            S12_unperturbed = forward_simulation(p, MonitorObject.DFT, frequencies)
            
            ## compare objective results
            print("|Ez|^2 -- adjoint solver: {}, traditional simulation: {}".format(adjsol_obj,S12_unperturbed))
            self.assertVectorsClose(adjsol_obj,S12_unperturbed,epsilon=1e-3)

            ## compute perturbed S12
            S12_perturbed = forward_simulation(p+dp, MonitorObject.DFT, frequencies)
            
            ## compare gradients
            if adjsol_grad.ndim < 2:
                adjsol_grad = np.expand_dims(adjsol_grad,axis=1)
            adj_scale = (dp[None,:]@adjsol_grad).flatten()
            fd_grad = S12_perturbed-S12_unperturbed
            print("Directional derivative -- adjoint solver: {}, FD: {}".format(adj_scale,fd_grad))
            tol = 0.3 if mp.is_single_precision() else 0.01
            self.assertVectorsClose(adj_scale,fd_grad,epsilon=tol)


    def test_adjoint_solver_eigenmode(self):
        print("*** TESTING EIGENMODE ADJOINT FEATURES ***")
        ## test the single frequency and multi frequency cases
        for frequencies in [[fcen], [1/1.58, fcen, 1/1.53]]:
            ## compute gradient using adjoint solver
            adjsol_obj, adjsol_grad = adjoint_solver(p, MonitorObject.EIGENMODE, frequencies)

            ## compute unperturbed S12
            S12_unperturbed = forward_simulation(p, MonitorObject.EIGENMODE, frequencies)

            ## compare objective results
            print("S12 -- adjoint solver: {}, traditional simulation: {}".format(adjsol_obj,S12_unperturbed))
            self.assertVectorsClose(adjsol_obj,S12_unperturbed,epsilon=1e-3)

            ## compute perturbed S12
            S12_perturbed = forward_simulation(p+dp, MonitorObject.EIGENMODE, frequencies)

            ## compare gradients
            if adjsol_grad.ndim < 2:
                adjsol_grad = np.expand_dims(adjsol_grad,axis=1)
            adj_scale = (dp[None,:]@adjsol_grad).flatten()
            fd_grad = S12_perturbed-S12_unperturbed
            print("Directional derivative -- adjoint solver: {}, FD: {}".format(adj_scale,fd_grad))
            tol = 0.04 if mp.is_single_precision() else 0.03
            self.assertVectorsClose(adj_scale,fd_grad,epsilon=tol)


    def test_gradient_backpropagation(self):
        print("*** TESTING BACKPROP FEATURES ***")
        for frequencies in [[fcen], [1/1.58, fcen, 1/1.53]]:
            ## filter/thresholding parameters
            filter_radius = 0.21985
            eta = 0.49093
            beta = 4.0698

            mapped_p = mapping(p,filter_radius,eta,beta)

            ## compute gradient using adjoint solver
            adjsol_obj, adjsol_grad = adjoint_solver(mapped_p, MonitorObject.EIGENMODE,frequencies)

            ## backpropagate the gradient
            if len(frequencies) > 1:
                bp_adjsol_grad = np.zeros(adjsol_grad.shape)
                for i in range(len(frequencies)):
                    bp_adjsol_grad[:,i] = tensor_jacobian_product(mapping,0)(p,filter_radius,eta,beta,adjsol_grad[:,i])
            else:
                bp_adjsol_grad = tensor_jacobian_product(mapping,0)(p,filter_radius,eta,beta,adjsol_grad)

            ## compute unperturbed S12
            S12_unperturbed = forward_simulation(mapped_p, MonitorObject.EIGENMODE,frequencies)

            ## compare objective results
            print("S12 -- adjoint solver: {}, traditional simulation: {}".format(adjsol_obj,S12_unperturbed))
            tol = 1e-2 if mp.is_single_precision() else 1e-3
            self.assertVectorsClose(adjsol_obj,S12_unperturbed,epsilon=tol)

            ## compute perturbed S12
            S12_perturbed = forward_simulation(mapping(p+dp,filter_radius,eta,beta), MonitorObject.EIGENMODE,frequencies)

            if bp_adjsol_grad.ndim < 2:
                bp_adjsol_grad = np.expand_dims(bp_adjsol_grad,axis=1)
            adj_scale = (dp[None,:]@bp_adjsol_grad).flatten()
            fd_grad = S12_perturbed-S12_unperturbed
            print("Directional derivative -- adjoint solver: {}, FD: {}".format(adj_scale,fd_grad))
            tol = 0.04 if mp.is_single_precision() else 0.03
            self.assertVectorsClose(adj_scale,fd_grad,epsilon=tol)


if __name__ == '__main__':
    unittest.main()
