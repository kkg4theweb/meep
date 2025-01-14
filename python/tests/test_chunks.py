import meep as mp
import unittest


class TestChunks(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = mp.make_output_directory()

    @classmethod
    def tearDownClass(cls):
        mp.delete_directory(cls.temp_dir)

    def test_chunks(self):
        sxy = 10
        cell = mp.Vector3(sxy, sxy, 0)

        fcen = 1.0  # pulse center frequency
        df = 0.1    # pulse width (in frequency)

        sources = [mp.Source(mp.GaussianSource(fcen, fwidth=df), mp.Ez, mp.Vector3())]

        dpml = 1.0
        pml_layers = [mp.PML(dpml)]
        resolution = 10

        sim = mp.Simulation(cell_size=cell,
                            boundary_layers=pml_layers,
                            sources=sources,
                            resolution=resolution,
                            split_chunks_evenly=False)

        sim.use_output_directory(self.temp_dir)

        top = mp.FluxRegion(center=mp.Vector3(0,+0.5*sxy-dpml), size=mp.Vector3(sxy-2*dpml,0), weight=+1.0)
        bot = mp.FluxRegion(center=mp.Vector3(0,-0.5*sxy+dpml), size=mp.Vector3(sxy-2*dpml,0), weight=-1.0)
        rgt = mp.FluxRegion(center=mp.Vector3(+0.5*sxy-dpml,0), size=mp.Vector3(0,sxy-2*dpml), weight=+1.0)
        lft = mp.FluxRegion(center=mp.Vector3(-0.5*sxy+dpml,0), size=mp.Vector3(0,sxy-2*dpml), weight=-1.0)

        tot_flux = sim.add_flux(fcen, 0, 1, top, bot, rgt, lft, decimation_factor=1)

        sim.run(until_after_sources=mp.stop_when_fields_decayed(50, mp.Ez, mp.Vector3(), 1e-5))

        sim.save_flux('tot_flux', tot_flux)
        sim1 = sim

        geometry = [mp.Block(center=mp.Vector3(),
                             size=mp.Vector3(sxy, sxy, mp.inf),
                             material=mp.Medium(index=3.5)),
                    mp.Block(center=mp.Vector3(),
                             size=mp.Vector3(sxy-2*dpml, sxy-2*dpml, mp.inf),
                             material=mp.air)]

        sim = mp.Simulation(cell_size=cell,
                            geometry=geometry,
                            boundary_layers=pml_layers,
                            sources=sources,
                            resolution=resolution,
                            chunk_layout=sim1)

        sim.use_output_directory(self.temp_dir)

        tot_flux = sim.add_flux(fcen, 0, 1, top, bot, rgt, lft, decimation_factor=1)

        sim.load_minus_flux('tot_flux', tot_flux)

        sim.run(until_after_sources=mp.stop_when_fields_decayed(50, mp.Ez, mp.Vector3(), 1e-5))

        places = 3 if mp.is_single_precision() else 7
        self.assertAlmostEqual(86.90826609300862, mp.get_fluxes(tot_flux)[0], places=places)


if __name__ == '__main__':
    unittest.main()
