from variant_filter import conflicts


def test_other_engines_rejected():
    assert conflicts("3.2.1 Starter -B-, Removing and Installing, 1.4L TSI Engine, Manual Transmission")
    assert conflicts("3.2.4 Starter, Removing and Installing, 2.0L TDI Engine, Manual Transmission")
    assert conflicts("3.2.8 Starter, Removing and Installing, 3.6L Engine with Automatic Transmission")
    assert conflicts("3.1.3 Overview - 2.0L TSI with Manual Transmission")


def test_own_car_and_generic_kept():
    assert not conflicts("3.2.7 Starter, Removing and Installing, 2.0L TSI Engine with DSG Transmission")
    assert not conflicts("3.1.7 Overview - 2.0L TSI Engine with DSG Transmission")
    assert not conflicts("3.2 Starter, Removing and Installing")
    assert not conflicts("")


def test_other_models_and_diesels_rejected():
    assert conflicts("3.2.11 Transmission, Removing, Tiguan from MY 2008, with 1.4L Gasoline")
    assert conflicts("3.2.7 Transmission, Removing, Passat from MY 2011 with Diesel Engine")
    assert not conflicts("2.1.1 Transmission, Removing, CC with FWD")
