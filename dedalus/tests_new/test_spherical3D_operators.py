
import pytest
import numpy as np
from dedalus.core import coords, distributor, basis, field, operators, arithmetic
from dedalus.tools.cache import CachedMethod
from mpi4py import MPI

comm = MPI.COMM_WORLD

## Ball
Nphi_range = [8]
Ntheta_range = [10]
Nr_range = [6]
radius_range = [1.5]
dealias_range = [1, 3/2]

def cartesian(phi, theta, r):
    x = r * np.sin(theta) * np.cos(phi)
    y = r * np.sin(theta) * np.sin(phi)
    z = r * np.cos(theta)
    return x, y, z

@CachedMethod
def build_ball(Nphi, Ntheta, Nr, radius, dealias):
    c = coords.SphericalCoordinates('phi', 'theta', 'r')
    d = distributor.Distributor((c,))
    b = basis.BallBasis(c, (Nphi, Ntheta, Nr), radius=radius, dealias=(dealias, dealias, dealias))
    phi, theta, r = b.local_grids()
    x, y, z = cartesian(phi, theta, r)
    return c, d, b, phi, theta, r, x, y, z

@pytest.mark.parametrize('Nphi', Nphi_range)
@pytest.mark.parametrize('Ntheta', Ntheta_range)
@pytest.mark.parametrize('Nr', Nr_range)
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_spherical_ell_product_scalar(Nphi, Ntheta, Nr, radius, dealias):
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    f = field.Field(dist=d, bases=(b,), dtype=np.complex128)
    g = field.Field(dist=d, bases=(b,), dtype=np.complex128)
    g.set_scales(b.domain.dealias)
    f['g'] = 3*x**2 + 2*y*z
    for ell in b.local_l:
        g['c'][:,ell,:]  = (ell+3)*f['c'][:,ell,:]
    func = lambda ell: ell+3
    h = operators.SphericalEllProduct(f, c, func).evaluate()
    assert np.allclose(h['g'], g['g'])

@pytest.mark.parametrize('Nphi', Nphi_range)
@pytest.mark.parametrize('Ntheta', Ntheta_range)
@pytest.mark.parametrize('Nr', Nr_range)
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_spherical_ell_product_vector(Nphi, Ntheta, Nr, radius, dealias):
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    f = field.Field(dist=d, bases=(b,), dtype=np.complex128)
    f['g'] = 3*x**2 + 2*y*z
    u = operators.Gradient(f, c).evaluate()
    uk0 = field.Field(dist=d, bases=(b,), tensorsig=(c,), dtype=np.complex128)
    uk0.set_scales(b.domain.dealias)
    uk0['g'] = u['g']
    v = field.Field(dist=d, bases=(b,), tensorsig=(c,), dtype=np.complex128)
    v.set_scales(b.domain.dealias)
    for ell in b.local_l:
        v['c'][0,:,ell,:] = (ell+2)*uk0['c'][0,:,ell,:]
        v['c'][1,:,ell,:] = (ell+4)*uk0['c'][1,:,ell,:]
        v['c'][2,:,ell,:] = (ell+3)*uk0['c'][2,:,ell,:]
    func = lambda ell: ell+3
    w = operators.SphericalEllProduct(u, c, func).evaluate()
    assert np.allclose(w['g'], v['g'])

@pytest.mark.parametrize('Nphi', Nphi_range)
@pytest.mark.parametrize('Ntheta', Ntheta_range)
@pytest.mark.parametrize('Nr', Nr_range)
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_convert_k2_vector(Nphi, Ntheta, Nr, radius, dealias):
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    u = field.Field(dist=d, bases=(b,), tensorsig=(c,), dtype=np.complex128)
    u.set_scales(b.domain.dealias)
    phi, theta, r = b.local_grids(b.domain.dealias)
    ct, st, cp, sp = np.cos(theta), np.sin(theta), np.cos(phi), np.sin(phi)
    u['g'][2] = r**2*st*(2*ct**2*cp-r*ct**3*sp+r**3*cp**3*st**5*sp**3+r*ct*st**2*(cp**3+sp**3))
    u['g'][1] = r**2*(2*ct**3*cp-r*cp**3*st**4+r**3*ct*cp**3*st**5*sp**3-1/16*r*np.sin(2*theta)**2*(-7*sp+np.sin(3*phi)))
    u['g'][0] = r**2*sp*(-2*ct**2+r*ct*cp*st**2*sp-r**3*cp**2*st**5*sp**3)
    v = operators.Laplacian(u, c).evaluate()
    u.require_coeff_space()
    v.require_coeff_space()
    w = (u + v).evaluate()
    assert np.allclose(w['g'],u['g']+v['g'])

@pytest.mark.parametrize('Nphi', Nphi_range)
@pytest.mark.parametrize('Ntheta', Ntheta_range)
@pytest.mark.parametrize('Nr', Nr_range)
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_transpose_grid_tensor(Nphi, Ntheta, Nr, radius, dealias):
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    u = field.Field(dist=d, bases=(b,), tensorsig=(c,), dtype=np.complex128)
    ct, st, cp, sp = np.cos(theta), np.sin(theta), np.cos(phi), np.sin(phi)
    u['g'][2] = r**2*st*(2*ct**2*cp-r*ct**3*sp+r**3*cp**3*st**5*sp**3+r*ct*st**2*(cp**3+sp**3))
    u['g'][1] = r**2*(2*ct**3*cp-r*cp**3*st**4+r**3*ct*cp**3*st**5*sp**3-1/16*r*np.sin(2*theta)**2*(-7*sp+np.sin(3*phi)))
    u['g'][0] = r**2*sp*(-2*ct**2+r*ct*cp*st**2*sp-r**3*cp**2*st**5*sp**3)
    T = operators.Gradient(u, c).evaluate()
    T.require_grid_space()
    Tg = np.transpose(np.copy(T['g']),(1,0,2,3,4))
    T = operators.TransposeComponents(T).evaluate()
    assert np.allclose(T['g'], Tg)

@pytest.mark.parametrize('Nphi', Nphi_range)
@pytest.mark.parametrize('Ntheta', Ntheta_range)
@pytest.mark.parametrize('Nr', Nr_range)
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_transpose_coeff_tensor(Nphi, Ntheta, Nr, radius, dealias):
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    u = field.Field(dist=d, bases=(b,), tensorsig=(c,), dtype=np.complex128)
    ct, st, cp, sp = np.cos(theta), np.sin(theta), np.cos(phi), np.sin(phi)
    u['g'][2] = r**2*st*(2*ct**2*cp-r*ct**3*sp+r**3*cp**3*st**5*sp**3+r*ct*st**2*(cp**3+sp**3))
    u['g'][1] = r**2*(2*ct**3*cp-r*cp**3*st**4+r**3*ct*cp**3*st**5*sp**3-1/16*r*np.sin(2*theta)**2*(-7*sp+np.sin(3*phi)))
    u['g'][0] = r**2*sp*(-2*ct**2+r*ct*cp*st**2*sp-r**3*cp**2*st**5*sp**3)
    T = operators.Gradient(u, c).evaluate()
    T.require_coeff_space()
    Tg = np.transpose(np.copy(T['g']),(1,0,2,3,4))
    T = operators.TransposeComponents(T).evaluate()
    assert np.allclose(T['g'], Tg)

# need higher resolution for the test function
@pytest.mark.parametrize('Nphi', [16])
@pytest.mark.parametrize('Ntheta', [16])
@pytest.mark.parametrize('Nr', [8])
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_interpolation_scalar(Nphi, Ntheta, Nr, radius, dealias):
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    f = field.Field(dist=d, bases=(b,), dtype=np.complex128)
    f['g'] = x**4 + 2*y**4 + 3*z**4
    h = operators.interpolate(f,r=1).evaluate()
    phi, theta, r = b.local_grids(b.domain.dealias)
    hg = radius**4*(3*np.cos(theta)**4 + np.cos(phi)**4*np.sin(theta)**4 + 2*np.sin(theta)**4*np.sin(phi)**4)
    assert np.allclose(h['g'], hg)

# need higher resolution for the test function
@pytest.mark.parametrize('Nphi', [16])
@pytest.mark.parametrize('Ntheta', [16])
@pytest.mark.parametrize('Nr', [8])
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_interpolation_vector(Nphi, Ntheta, Nr, radius, dealias):
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    u = field.Field(dist=d, bases=(b,), tensorsig=(c,), dtype=np.complex128)
    ct, st, cp, sp = np.cos(theta), np.sin(theta), np.cos(phi), np.sin(phi)
    u['g'][2] = r**2*st*(2*ct**2*cp-r*ct**3*sp+r**3*cp**3*st**5*sp**3+r*ct*st**2*(cp**3+sp**3))
    u['g'][1] = r**2*(2*ct**3*cp-r*cp**3*st**4+r**3*ct*cp**3*st**5*sp**3-1/16*r*np.sin(2*theta)**2*(-7*sp+np.sin(3*phi)))
    u['g'][0] = r**2*sp*(-2*ct**2+r*ct*cp*st**2*sp-r**3*cp**2*st**5*sp**3)
    v = operators.interpolate(u,r=1).evaluate()
    vg = 0*v['g']
    phi, theta, r = b.local_grids(b.domain.dealias)
    ct, st, cp, sp = np.cos(theta), np.sin(theta), np.cos(phi), np.sin(phi)
    vg[0] = radius**2*sp*(-2*ct**2+radius*ct*cp*st**2*sp-radius**3*cp**2*st**5*sp**3)
    vg[1] = radius**2*(2*ct**3*cp-radius*cp**3*st**4+radius**3*ct*cp**3*st**5*sp**3-1/16*radius*np.sin(2*theta)**2*(-7*sp+np.sin(3*phi)))
    vg[2] = radius**2*st*(2*ct**2*cp-radius*ct**3*sp+radius**3*cp**3*st**5*sp**3+radius*ct*st**2*(cp**3+sp**3))
    assert np.allclose(v['g'], vg)

@pytest.mark.parametrize('Nphi', Nphi_range)
@pytest.mark.parametrize('Ntheta', Ntheta_range)
@pytest.mark.parametrize('Nr', Nr_range)
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_interpolation_tensor(Nphi, Ntheta, Nr, radius, dealias):
    # Note: In this test, the boundary restriction of the tensor does not depend on the radius
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    T = field.Field(dist=d, bases=(b,), tensorsig=(c,c), dtype=np.complex128)
    T['g'][2,2] = (6*x**2+4*y*z)/r**2
    T['g'][2,1] = T['g'][1,2] = -2*(y**3+x**2*(y-3*z)-y*z**2)/(r**3*np.sin(theta))
    T['g'][2,0] = T['g'][0,2] = 2*x*(z-3*y)/(r**2*np.sin(theta))
    T['g'][1,1] = 6*x**2/(r**2*np.sin(theta)**2) - (6*x**2+4*y*z)/r**2
    T['g'][1,0] = T['g'][0,1] = -2*x*(x**2+y**2+3*y*z)/(r**3*np.sin(theta)**2)
    T['g'][0,0] = 6*y**2/(x**2+y**2)
    A = operators.interpolate(T,r=1).evaluate()
    Ag = 0*A['g']
    phi, theta, r = b.local_grids(b.domain.dealias)
    x, y, z = cartesian(phi, theta, r)
    Ag[2,2] = 2*np.sin(theta)*(3*np.cos(phi)**2*np.sin(theta)+2*np.cos(theta)*np.sin(phi))
    Ag[2,1] = Ag[1,2] = 6*np.cos(theta)*np.cos(phi)**2*np.sin(theta) + 2*np.cos(2*theta)*np.sin(phi)
    Ag[2,0] = Ag[0,2] = 2*np.cos(phi)*(np.cos(theta) - 3*np.sin(theta)*np.sin(phi))
    Ag[1,1] = 2*np.cos(theta)*(3*np.cos(theta)*np.cos(phi)**2 - 2*np.sin(theta)*np.sin(phi))
    Ag[1,0] = Ag[0,1] = -2*np.cos(phi)*(np.sin(theta) + 3*np.cos(theta)*np.sin(phi))
    Ag[0,0] = 6*np.sin(phi)**2
    assert np.allclose(A['g'],Ag)

# need higher resolution for the test function
@pytest.mark.parametrize('Nphi', [16])
@pytest.mark.parametrize('Ntheta', [16])
@pytest.mark.parametrize('Nr', [8])
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_radial_component_vector(Nphi, Ntheta, Nr, radius, dealias):
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    u = field.Field(dist=d, bases=(b,), tensorsig=(c,), dtype=np.complex128)
    ct, st, cp, sp = np.cos(theta), np.sin(theta), np.cos(phi), np.sin(phi)
    u['g'][2] = r**2*st*(2*ct**2*cp-r*ct**3*sp+r**3*cp**3*st**5*sp**3+r*ct*st**2*(cp**3+sp**3))
    u['g'][1] = r**2*(2*ct**3*cp-r*cp**3*st**4+r**3*ct*cp**3*st**5*sp**3-1/16*r*np.sin(2*theta)**2*(-7*sp+np.sin(3*phi)))
    u['g'][0] = r**2*sp*(-2*ct**2+r*ct*cp*st**2*sp-r**3*cp**2*st**5*sp**3)
    v = operators.RadialComponent(operators.interpolate(u,r=1)).evaluate()
    phi, theta, r = b.local_grids(b.domain.dealias)
    ct, st, cp, sp = np.cos(theta), np.sin(theta), np.cos(phi), np.sin(phi)
    vg = radius**2*st*(2*ct**2*cp-radius*ct**3*sp+radius**3*cp**3*st**5*sp**3+radius*ct*st**2*(cp**3+sp**3))
    assert np.allclose(v['g'], vg)

@pytest.mark.parametrize('Nphi', Nphi_range)
@pytest.mark.parametrize('Ntheta', Ntheta_range)
@pytest.mark.parametrize('Nr', Nr_range)
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_radial_component_tensor(Nphi, Ntheta, Nr, radius, dealias):
    # Note: In this test, the boundary restriction of the tensor does not depend on the radius
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    T = field.Field(dist=d, bases=(b,), tensorsig=(c,c), dtype=np.complex128)
    T['g'][2,2] = (6*x**2+4*y*z)/r**2
    T['g'][2,1] = T['g'][1,2] = -2*(y**3+x**2*(y-3*z)-y*z**2)/(r**3*np.sin(theta))
    T['g'][2,0] = T['g'][0,2] = 2*x*(z-3*y)/(r**2*np.sin(theta))
    T['g'][1,1] = 6*x**2/(r**2*np.sin(theta)**2) - (6*x**2+4*y*z)/r**2
    T['g'][1,0] = T['g'][0,1] = -2*x*(x**2+y**2+3*y*z)/(r**3*np.sin(theta)**2)
    T['g'][0,0] = 6*y**2/(x**2+y**2)
    A = operators.RadialComponent(operators.interpolate(T,r=1)).evaluate()
    Ag = 0*A['g']
    phi, theta, r = b.local_grids(b.domain.dealias)
    x, y, z = cartesian(phi, theta, r)
    Ag[2] = 2*np.sin(theta)*(3*np.cos(phi)**2*np.sin(theta)+2*np.cos(theta)*np.sin(phi))
    Ag[1] = 6*np.cos(theta)*np.cos(phi)**2*np.sin(theta) + 2*np.cos(2*theta)*np.sin(phi)
    Ag[0] = 2*np.cos(phi)*(np.cos(theta) - 3*np.sin(theta)*np.sin(phi))
    assert np.allclose(A['g'],Ag)

# need higher resolution for the test function
@pytest.mark.parametrize('Nphi', [16])
@pytest.mark.parametrize('Ntheta', [16])
@pytest.mark.parametrize('Nr', [8])
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_angular_component_vector(Nphi, Ntheta, Nr, radius, dealias):
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    u = field.Field(dist=d, bases=(b,), tensorsig=(c,), dtype=np.complex128)
    ct, st, cp, sp = np.cos(theta), np.sin(theta), np.cos(phi), np.sin(phi)
    u['g'][2] = r**2*st*(2*ct**2*cp-r*ct**3*sp+r**3*cp**3*st**5*sp**3+r*ct*st**2*(cp**3+sp**3))
    u['g'][1] = r**2*(2*ct**3*cp-r*cp**3*st**4+r**3*ct*cp**3*st**5*sp**3-1/16*r*np.sin(2*theta)**2*(-7*sp+np.sin(3*phi)))
    u['g'][0] = r**2*sp*(-2*ct**2+r*ct*cp*st**2*sp-r**3*cp**2*st**5*sp**3)
    v = operators.AngularComponent(operators.interpolate(u,r=1)).evaluate()
    vg = 0*v['g']
    phi, theta, r = b.local_grids(b.domain.dealias)
    ct, st, cp, sp = np.cos(theta), np.sin(theta), np.cos(phi), np.sin(phi)
    vg[0] = radius**2*sp*(-2*ct**2+radius*ct*cp*st**2*sp-radius**3*cp**2*st**5*sp**3)
    vg[1] = radius**2*(2*ct**3*cp-radius*cp**3*st**4+radius**3*ct*cp**3*st**5*sp**3-1/16*radius*np.sin(2*theta)**2*(-7*sp+np.sin(3*phi)))
    assert np.allclose(v['g'], vg)

@pytest.mark.parametrize('Nphi', Nphi_range)
@pytest.mark.parametrize('Ntheta', Ntheta_range)
@pytest.mark.parametrize('Nr', Nr_range)
@pytest.mark.parametrize('radius', radius_range)
@pytest.mark.parametrize('dealias', dealias_range)
def test_ball_angular_component_tensor(Nphi, Ntheta, Nr, radius, dealias):
    # Note: In this test, the boundary restriction of the tensor does not depend on the radius
    c, d, b, phi, theta, r, x, y, z = build_ball(Nphi, Ntheta, Nr, radius, dealias)
    T = field.Field(dist=d, bases=(b,), tensorsig=(c,c), dtype=np.complex128)
    T['g'][2,2] = (6*x**2+4*y*z)/r**2
    T['g'][2,1] = T['g'][1,2] = -2*(y**3+x**2*(y-3*z)-y*z**2)/(r**3*np.sin(theta))
    T['g'][2,0] = T['g'][0,2] = 2*x*(z-3*y)/(r**2*np.sin(theta))
    T['g'][1,1] = 6*x**2/(r**2*np.sin(theta)**2) - (6*x**2+4*y*z)/r**2
    T['g'][1,0] = T['g'][0,1] = -2*x*(x**2+y**2+3*y*z)/(r**3*np.sin(theta)**2)
    T['g'][0,0] = 6*y**2/(x**2+y**2)
    A = operators.AngularComponent(operators.interpolate(T,r=1),index=1).evaluate()
    Ag = 0*A['g']
    phi, theta, r = b.local_grids(b.domain.dealias)
    x, y, z = cartesian(phi, theta, r)
    Ag[2,1] = 6*np.cos(theta)*np.cos(phi)**2*np.sin(theta) + 2*np.cos(2*theta)*np.sin(phi)
    Ag[2,0] = 2*np.cos(phi)*(np.cos(theta) - 3*np.sin(theta)*np.sin(phi))
    Ag[1,1] = 2*np.cos(theta)*(3*np.cos(theta)*np.cos(phi)**2 - 2*np.sin(theta)*np.sin(phi))
    Ag[1,0] = Ag[0,1] = -2*np.cos(phi)*(np.sin(theta) + 3*np.cos(theta)*np.sin(phi))
    Ag[0,0] = 6*np.sin(phi)**2
    assert np.allclose(A['g'],Ag)
