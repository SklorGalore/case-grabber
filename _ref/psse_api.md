# PSSE API Command Cheat Sheet

[TOC]

## Non-Engineering

### Default Values

The following commands are applicable to python only. Internally, the values are commonly stored as _c, _i, _f

#### Get Default Character

Python syntax: `cdef = getdefaultchar()`

#### Get Default Integer

Python syntax: `idef = getdefaultint()`

#### Get Default Real

Python syntax: `rdef = getdefaultreal()`

## Power Flow

The following section contains helpful snippets for power flow data modification. Note that many commands may return an error code `ierr` which can be useful for determining if the command ran correctly or not.

### Power Flow Operation

#### Newton-Raphson Fixed Slope Decoupled Solution

Batch syntax: `BAT_FDNS OPTIONS(1)..OPTIONS(8)`

Python syntax: `ierr = fdns(options)`

```python
# Tap adjustment
tap: int = 0            # 0 = disable
                        # 1 = enable stepping adjustment
                        # 2 = enable direct adjustment
                        # [default: current tap adjustment option setting]

# Area interchange adjustment
area: int = 0           # 0 = disable
                        # 1 = enable using tie line flows only
                        # 2 = enable using tie line flows and loads
                        # [default: current area interchange option setting]

# Phase shift adjustment
phase: int = 0          # 0 = disable
                        # 1 = enable
                        # [default: current phase shift adjustment option setting]

# DC tap adjustment
dc_tap: int = 0         # 0 = disable
                        # 1 = enable
                        # [default: current DC tap adjustment option setting]

# Switched shunt adjustment
shunt: int = 0          # 0 = disable
                        # 1 = enable
                        # 2 = enable continuous mode, disable discrete mode
                        # [default: current switched shunt adjustment option setting]

# Flat start
flat: int = 0           # 0 = do not flat start [default]
                        # 1 = flat start
                        # 2 = flat start, then estimate voltage magnitudes
                        # 3 = flat start, then estimate voltage phase angles
                        # 4 = flat start, then estimate voltage magnitudes and phase angles

# VAR limits
var_limits: int = 99    #  0 = apply VAR limits immediately
                        # >0 = apply VAR limits on iteration n (or sooner if mismatch gets small)
                        # -1 = ignore VAR limits
                        # [default: 99]

# Non-divergent solution
non_divergent: int = 0  # 0 = disable
                        # 1 = enable
                        # [default: current non-divergent solution option setting]

ierr = psspy.fdns(
    [
        tap,
        area,
        phase,
        dc_tap,
        shunt,
        flat,
        var_limits,
        non_divergent,
    ]
)
```

#### Write to .RAW File

Batch syntax: `BAT_RAWD_2 SID ALL STATUS(1)..STATUS(7) OUT OFILE`

Python syntax: `ierr = rawd_2(sid, all, status, out, ofile)`

```python
# Subsystem selection
sid: int = 0             # Subsystem identifier, valid range 0-11 [default: 0]
all_buses: int = 1       # 0 = process only buses in subsystem SID
                         # 1 = process all buses [default: 1]

# Bus options
type_4: int = 1          # Include records for Type 4 buses
                         # 0 = no
                         # 1 = yes [default]

# Branch options
out_service: int = 1     # Include records for out-of-service branches
                         # 0 = no
                         # 1 = yes [default]

# Subsystem equipment
equipment: int = 1       # Include records for equipment in the subsystem
                         # 0 = no
                         # 1 = yes [default]

# Tie branches
ties: int = 0            # Include records for subsystem tie branches
                         # 0 = no [default]
                         # 1 = yes

# Load records (honored when ALL = 0)
loads: int = 0           # 0 = all loads at subsystem buses [default]
                         # 1 = subsystem loads at all buses
                         # 2 = all loads at subsystem buses and
                         #     subsystem loads at non-subsystem buses

# Bus identifiers
bus_names: int = 0       # Use bus names as bus identifiers
                         # 0 = no [default]
                         # 1 = yes

# RAW data file type
raw_type: int = 0        # 0 = READ with IC=0 [default]
                         # 1 = READ with IC=1
                         # 2 = RDCH; include all data categories
                         # 3 = RDCH; exclude substation data category
                         # 4 = RDCH; include only substation data category

ierr = psspy.rawd_2(
    sid,
    all_buses,
    [
        type_4,
        out_service,
        equipment,
        ties,
        loads,
        bus_names,
        raw_type,
    ],
    "case.raw",
)
```

#### Case Scaling

Batch syntax: `BAT_SCAL_4 SID ALL APIOPT STATUS(1)..STATUS(6) SCALVAL(1)..SCALVAL(7)`

Python syntax: `ierr, totals, moto= scal_4(sid, all, apiopt, status, scalval)`

```python
# Subsystem selection
sid: int = 0             # Subsystem identifier, valid range 0-11 [default: 0]
all_buses: int = 1       # 0 = process only buses in subsystem SID
                         # 1 = process all buses [default: 1]

# API operation
apiopt: int = 0          # 0 = initialize, scale, and perform housekeeping [default]
                         # 1 = initialize for scaling only
                         # 2 = run scaling and post-processing housekeeping

# Load interruptibility scaling
interruptible: int = 0   # 0 = scale interruptible and non-interruptible loads [default]
                         # 1 = scale only non-interruptible loads
                         # 2 = scale only interruptible loads

# Load component scaling
load_component: int = 0  # 0 = scale in-service net load [default]
                         # 1 = scale only in-service load
                         # 2 = scale only in-service distributed generation

# Baseloaded generation scaling
base_load: int = 0       # 0 = scale all machines, ignore base load flags [default]
                         # 1 = scale all machines, honor base load flags
                         # 2 = scale only non-base-loaded machines
                         # 3 = scale only base-loaded machines, ignore base load flags
                         # 4 = scale only base-loaded machines, honor base load flags

# Active power scaling method
scale_method: int = 0    # 0 = no scaling [default]
                         # 1 = specify new total powers
                         # 2 = specify percent changes
                         # 3 = specify incremental powers

# Machine power limits
power_limits: int = 0    # 0 = ignore machine power limits [default]
                         # 1 = enforce machine power limits

# Reactive load scaling method
reactive_method: int = 0 # 0 = no change [default]
                         # 1 = maintain constant P/Q ratio
                         # 2 = specify new total Q load
                         # 3 = specify percent change
                         # 4 = specify new power factor
                         # 5 = specify incremental Q load

# Scaling targets
load_mw: float = 0.0     # Load MW total / percent / increment
gen_mw: float = 0.0      # Generation MW total / percent / increment
shunt_mw: float = 0.0    # Shunt MW total / percent / increment
reactor_mvar: float = 0.0 # Reactor Mvar total / percent / increment
capacitor_mvar: float = 0.0 # Capacitor Mvar total / percent / increment
motor_mw: float = 0.0    # Motor load MW total / percent / increment
load_mvar: float = 0.0   # Reactive load scaling parameter

ierr, totals, moto = psspy.scal_4(
    sid,
    all_buses,
    apiopt,
    [
        interruptible,
        load_component,
        base_load,
        scale_method,
        power_limits,
        reactive_method,
    ],
    [
        load_mw,
        gen_mw,
        shunt_mw,
        reactor_mvar,
        capacitor_mvar,
        motor_mw,
        load_mvar,
    ],
)
```



### Power Flow Data

#### Branch Data

Modify or add a non-transformer branch.

Batch syntax: `BAT_BRANCH_DATA_3 IBUS JBUS CKT INTGAR(1)..INTGAR(6) REALAR(1)..REALAR(12) RATINGS(1)..RATINGS(12) NAMEAR`

Python syntax: `ierr = branch_data_3(ibus, jbus, ckt, intgar, realar, ratings, namear)`

Snippet:

```python
# Branch identifiers
i_bus: int = 1       # Bus number of "from" bus
j_bus: int = 2       # Bus number of "to" bus
ckt: str = "1"       # Circuit identifier [default: "1"]

# Integer data
st: int = 1          # Branch status: 1 = in service, 0 = out of service [default: 1]
met_bus: int = i_bus # Metered end bus number [default: i_bus]
o_1: int = 1         # ID number of owner 1 [default: owner of i_bus]
o_2: int = 0         # ID number of owner 2 [default: 0]
o_3: int = 0         # ID number of owner 3 [default: 0]
o_4: int = 0         # ID number of owner 4 [default: 0]

# Branch impedance and shunt data
r: float = 0.0       # Branch resistance [default: 0]
x: float = 0.0001    # Branch reactance [default: THRSHZ, or 0.0001 if THRSHZ = 0]
b: float = 0.0       # Total line charging [default: 0]
g_i: float = 0.0     # Real line shunt at i_bus [default: 0]
b_i: float = 0.0     # Imaginary line shunt at i_bus [default: 0]
g_j: float = 0.0     # Real line shunt at j_bus [default: 0]
b_j: float = 0.0     # Imaginary line shunt at j_bus [default: 0]
length: float = 0.0  # Length of the line, typically in miles [default: 0]

# Ownership fractions
f1: float = 1.0      # Fractional ownership of owner 1 [default: 1]
f2: float = 0.0      # Fractional ownership of owner 2 [default: 0]
f3: float = 0.0      # Fractional ownership of owner 3 [default: 0]
f4: float = 0.0      # Fractional ownership of owner 4 [default: 0]

# Ratings
rate1: float = 0.0   # Rating set 1 [default: 0]
rate2: float = 0.0   # Rating set 2 [default: 0]
rate3: float = 0.0   # Rating set 3 [default: 0]
rate4: float = 0.0   # Rating set 4 [default: 0]
rate5: float = 0.0   # Rating set 5 [default: 0]
rate6: float = 0.0   # Rating set 6 [default: 0]
rate7: float = 0.0   # Rating set 7 [default: 0]
rate8: float = 0.0   # Rating set 8 [default: 0]
rate9: float = 0.0   # Rating set 9 [default: 0]
rate10: float = 0.0  # Rating set 10 [default: 0]
rate11: float = 0.0  # Rating set 11 [default: 0]
rate12: float = 0.0  # Rating set 12 [default: 0]

ierr = psspy.branch_data_3(
    i_bus,
    j_bus,
    ckt,
    [
        st,
        met_bus,
        o_1,
        o_2,
        o_3,
        o_4,
    ],
    [
        r,
        x,
        b,
        g_i,
        b_i,
        g_j,
        b_j,
        length,
        f1,
        f2,
        f3,
        f4,
    ],
    [
        rate1,
        rate2,
        rate3,
        rate4,
        rate5,
        rate6,
        rate7,
        rate8,
        rate9,
        rate10,
        rate11,
        rate12,
    ],
)
```

#### Bus Data

Modify or add a bus.

Batch syntax: `BAT_BUS_DATA_4 IBUS INODE INTGAR(1)..INTGAR(4) REALAR(1)..REALAR(7) 'NAME'`

Python syntax: `ierr = bus_data_4(ibus, inode, intgar, realar, name)`

Snippet:

```python
# Bus identifiers
i_bus: int = 1        # Bus number (no default)
i_node: int = 0       # Bus section node number (no default)

# Integer data
ide: int = 1          # Bus type code [default: 1]
area: int = 1         # Area number [default: 1]
zone: int = 1         # Zone number [default: 1]
owner: int = 1        # Owner number [default: 1]

# Real data
baskv: float = 0.0    # Bus base voltage in kV [default: 0.0]
vm: float = 1.0       # Bus voltage magnitude in pu [default: 1.0]
va: float = 0.0       # Bus voltage phase angle in degrees [default: 0.0]
nmaxv: float = 1.1    # Normal voltage magnitude high limit in pu [default: 1.1]
nminv: float = 0.9    # Normal voltage magnitude low limit in pu [default: 0.9]
emaxv: float = 1.1    # Emergency voltage magnitude high limit in pu [default: 1.1]
eminv: float = 0.9    # Emergency voltage magnitude low limit in pu [default: 0.9]

# Bus name
name: str = ""        # Bus name, maximum 12 characters [default: blank]

ierr = psspy.bus_data_4(
    i_bus,
    i_node,
    [
        ide,
        area,
        zone,
        owner,
    ],
    [
        baskv,
        vm,
        va,
        nmaxv,
        nminv,
        emaxv,
        eminv,
    ],
    name,
)
```

#### Load Data

Batch syntax: `BAT_LOAD_DATA_6 IBUS ID INTGAR(1)..INTGAR(7) REALAR(1)..REALAR(8) LODTYP`

Python syntax: `ierr = load_data_6(ibus, id, intgar, realar, lodtyp)`

```python
# Load identifiers
i_bus: int = 1          # Bus number (no default)
load_id: str = "1"      # Load identifier, maximum 2 characters [default: "1"]

# Integer data
status: int = 1         # Load status [default: 1]
area: int = 1           # Area number [default: area of i_bus]
zone: int = 1           # Zone number [default: zone of i_bus]
owner: int = 1          # Owner number [default: owner of i_bus]
scale: int = 1          # Load scaling flag: 0 = fixed, 1 = scalable [default: 1]
intrpt: int = 0         # Interruptible load flag: 0 = non-interruptible, 1 = interruptible [default: 0]
dgnflg: int = 0         # Distributed generation flag: 0 = out of service, 1 = in service [default: 0]

# Load data
pl: float = 0.0         # Constant power active load [default: 0.0]
ql: float = 0.0         # Constant power reactive load [default: 0.0]
ip: float = 0.0         # Constant current active load [default: 0.0]
iq: float = 0.0         # Constant current reactive load [default: 0.0]
yp: float = 0.0         # Constant admittance active load [default: 0.0]
yq: float = 0.0         # Constant admittance reactive load [default: 0.0]
pg: float = 0.0         # Distributed generation real power [default: 0.0]
qg: float = 0.0         # Distributed generation reactive power [default: 0.0]

# Load type
lodtyp: str = ""        # Load type description, maximum 12 characters [default: blank]

ierr = psspy.load_data_6(
    i_bus,
    load_id,
    [
        status,
        area,
        zone,
        owner,
        scale,
        intrpt,
        dgnflg,
    ],
    [
        pl,
        ql,
        ip,
        iq,
        yp,
        yq,
        pg,
        qg,
    ],
    lodtyp,
)
```

#### Machine Data

Batch syntax: `BAT_MACHINE_DATA_4 IBUS 'ID' INTGAR(1)..INTGAR(7) REALAR(1)..REALAR(17), NAME`

Python syntax: `ierr = machine_data_4(ibus, id, intgar, realar, name)`

```python
# Machine identifiers
i_bus: int = 1          # Bus number (no default)
machine_id: str = "1"   # Machine identifier, maximum 2 characters [default: "1"]

# Integer data
stat: int = 1           # Machine status [default: 1]
o_1: int = 1            # First owner number [default: owner of i_bus]
o_2: int = 0            # Second owner number [default: 0]
o_3: int = 0            # Third owner number [default: 0]
o_4: int = 0            # Fourth owner number [default: 0]
wmod: int = 0           # Non-conventional machine reactive power limits mode [default: 0]
basflg: int = 0         # Baseloaded machine flag

# Machine power data
pg: float = 0.0         # Machine active power [default: 0.0]
qg: float = 0.0         # Machine reactive power [default: 0.0]
qt: float = 9999.0      # Machine reactive power upper limit [default: 9999.0]
qb: float = -9999.0     # Machine reactive power lower limit [default: -9999.0]
pt: float = 9999.0      # Machine active power upper limit [default: 9999.0]
pb: float = -9999.0     # Machine active power lower limit [default: -9999.0]
mbase: float = sbase    # Machine MVA base [default: system SBASE]

# Machine impedance
zr: float = 0.0         # Machine resistance [default: 0.0]
zx: float = 1.0         # Machine reactance [default: 1.0]

# Step-up transformer data
rt: float = 0.0         # Step-up transformer resistance [default: 0.0]
xt: float = 0.0         # Step-up transformer reactance [default: 0.0]
gtap: float = 1.0       # Step-up transformer tap ratio [default: 1.0]

# Ownership fractions
f1: float = 1.0         # First owner fraction [default: 1.0]
f2: float = 1.0         # Second owner fraction [default: 1.0]
f3: float = 1.0         # Third owner fraction [default: 1.0]
f4: float = 1.0         # Fourth owner fraction [default: 1.0]

# Non-conventional machine data
wpf: float = 1.0        # Non-conventional machine power factor [default: 1.0]

ierr = psspy.machine_data_4(
    i_bus,
    machine_id,
    [
        stat,
        o_1,
        o_2,
        o_3,
        o_4,
        wmod,
        basflg,
    ],
    [
        pg,
        qg,
        qt,
        qb,
        pt,
        pb,
        mbase,
        zr,
        zx,
        rt,
        xt,
        gtap,
        f1,
        f2,
        f3,
        f4,
        wpf,
    ],
)
```

#### Two-Winding Data

Batch syntax: `BAT_MACHINE_DATA_4 IBUS 'ID' INTGAR(1)..INTGAR(7) REALAR(1)..REALAR(17), NAME`

Python syntax: `ierr, realaro = two_winding_data_6(ibus, jbus, ckt, intgar, realari, ratings, namear, vgrpar)`

```python
# Transformer identifiers
i_bus: int = 1          # Bus number of "from" bus (no default)
j_bus: int = 2          # Bus number of "to" bus (no default)
ckt: str = "1"          # Circuit identifier [default: "1"]

# Integer data
stat: int = 1           # Branch status [default: 1]
met_bus: int = i_bus    # Metered end bus number (i_bus or j_bus) [default: i_bus]
o_1: int = 1            # First owner number [default: owner of i_bus]
o_2: int = 0            # Second owner number [default: 0]
o_3: int = 0            # Third owner number [default: 0]
o_4: int = 0            # Fourth owner number [default: 0]
ntp1: int = 33          # Number of tap positions [default: 33]
tab1: int = 0           # Impedance correction table number [default: 0]
wn1_bus: int = i_bus    # Winding one side bus number [default: i_bus]
cont1: int = 0          # Controlled bus number [default: 0]
node1: int = 0          # Controlled node number [default: 0]
sicod1: int = 1         # Sign for controlled bus location [default: 1]
cod1: int = 0           # Adjustment control mode flag (-5 through +5) [default: 0]
cw: int = 1             # Winding data I/O code [default: 1]
cz: int = 1             # Impedance data I/O code [default: 1]
cm: int = 1             # Magnetizing admittance data I/O code [default: 1]

# Transformer impedance data
r_1_2: float = 0.0      # Nominal transformer resistance [default: 0.0]
x_1_2: float = 0.0001   # Nominal transformer reactance [default: THRSHZ, or 0.0001 if THRSHZ = 0]
sbs_1_2: float = 100.0  # Winding base MVA [default: system SBASE]

# Winding data
windv1: float = 1.0     # Winding 1 ratio/voltage [default: 1.0 for CW = 1 or 3]
nomv1: float = 0.0      # Winding 1 nominal voltage [default: 0.0]
ang1: float = 0.0       # Winding 1 phase shift angle [default: 0.0]
windv2: float = 1.0     # Winding 2 ratio/voltage [default: 1.0 for CW = 1 or 3]
nomv2: float = 0.0      # Winding 2 nominal voltage [default: 0.0]

# Ownership fractions
f1: float = 1.0         # First owner fraction [default: 1.0]
f2: float = 1.0         # Second owner fraction [default: 1.0]
f3: float = 1.0         # Third owner fraction [default: 1.0]
f4: float = 1.0         # Fourth owner fraction [default: 1.0]

# Magnetizing admittance data
mag1: float = 0.0       # Magnetizing conductance / no-load losses [default: 0.0]
mag2: float = 0.0       # Magnetizing susceptance / exciting current [default: 0.0]

# Winding 1 adjustment limits
rma1: float = 1.1       # Winding 1 ratio/angle high limit [default: 1.1]
rmi1: float = 0.9       # Winding 1 ratio/angle low limit [default: 0.9]
vma1: float = 1.1       # Voltage or flow upper limit [default: 1.1]
vmi1: float = 0.9       # Voltage or flow lower limit [default: 0.9]

# Load drop compensation
cr1: float = 0.0        # Load drop compensating resistance [default: 0.0]
cx1: float = 0.0        # Load drop compensating reactance [default: 0.0]

# Winding connection
cnxa1: float = 0.0      # Winding connection angle [default: 0.0]

# Ratings
rate1: float = 0.0      # Rating set 1 [default: 0.0]
rate2: float = 0.0      # Rating set 2 [default: 0.0]
rate3: float = 0.0      # Rating set 3 [default: 0.0]
rate4: float = 0.0      # Rating set 4 [default: 0.0]
rate5: float = 0.0      # Rating set 5 [default: 0.0]
rate6: float = 0.0      # Rating set 6 [default: 0.0]
rate7: float = 0.0      # Rating set 7 [default: 0.0]
rate8: float = 0.0      # Rating set 8 [default: 0.0]
rate9: float = 0.0      # Rating set 9 [default: 0.0]
rate10: float = 0.0     # Rating set 10 [default: 0.0]
rate11: float = 0.0     # Rating set 11 [default: 0.0]
rate12: float = 0.0     # Rating set 12 [default: 0.0]

# Transformer identification
name: str = ""          # Transformer name, maximum 40 characters [default: blank]
vgrp: str = ""          # Vector group name, maximum 12 characters [default: blank]

ierr = psspy.two_winding_data_6(
    i_bus,
    j_bus,
    ckt,
    [
        stat,
        met_bus,
        o_1,
        o_2,
        o_3,
        o_4,
        ntp1,
        tab1,
        wn1_bus,
        cont1,
        node1,
        sicod1,
        cod1,
        cw,
        cz,
        cm,
    ],
    [
        r_1_2,
        x_1_2,
        sbs_1_2,
        windv1,
        nomv1,
        ang1,
        windv2,
        nomv2,
        f1,
        f2,
        f3,
        f4,
        mag1,
        mag2,
        rma1,
        rmi1,
        vma1,
        vmi1,
        cr1,
        cx1,
        cnxa1,
    ],
    [
        rate1,
        rate2,
        rate3,
        rate4,
        rate5,
        rate6,
        rate7,
        rate8,
        rate9,
        rate10,
        rate11,
        rate12,
    ],
    name,
    vgrp,
)
```

#### Three-winding Transformer Data (Single Winding)

Batch syntax: `BAT_THREE_WND_WINDING_DATA_5 IBUS JBUS KBUS CKT WARG INTGAR(1)..INTGAR(6) REALAR(1)..REALAR(10) RATINGS(1)..RATINGS(12)`

Python syntax: `ierr, realaro = three_wnd_winding_data_5(ibus, jbus, kbus, ckt, warg, intgar, realari, ratings)`

```python
# Transformer identifiers
i_bus: int = 1          # Bus number of one transformer bus (no default)
j_bus: int = 2          # Bus number of another transformer bus (no default)
k_bus: int = 3          # Bus number of the third transformer bus (no default)
ckt: str = "1"          # Transformer circuit identifier [default: "1"]
warg: int = 1           # Winding number to modify: 1, 2, or 3 (no default)

# Integer data for selected winding
ntp: int = 33           # Number of tap positions [default: 33]
tab: int = 0            # Impedance correction table number [default: 0]
cont: int = 0           # Controlled bus number [default: 0]
node: int = 0           # Controlled node number [default: 0]
sicod: int = 1          # Sign for controlled bus location [default: 1]
cod: int = 0            # Adjustment control mode flag (-3 through +3, -5, or +5) [default: 0]

# Selected winding data
windv: float = 1.0      # Winding ratio/voltage [default: 1.0 for CW = 1 or 3]
nomv: float = 0.0       # Winding nominal voltage [default: 0.0]
ang: float = 0.0        # Winding phase shift angle [default: 0.0]

# Winding adjustment limits
rma: float = 1.1        # Winding ratio/angle high limit [default: 1.1]
rmi: float = 0.9        # Winding ratio/angle low limit [default: 0.9]
vma: float = 1.1        # Winding voltage or flow upper limit [default: 1.1]
vmi: float = 0.9        # Winding voltage or flow lower limit [default: 0.9]

# Load drop compensation
cr: float = 0.0         # Winding load drop compensating resistance [default: 0.0]
cx: float = 0.0         # Winding load drop compensating reactance [default: 0.0]

# Winding connection
cnxa: float = 0.0       # Winding connection angle [default: 0.0]

# Winding ratings
rate1: float = 0.0      # Rating set 1 [default: 0.0]
rate2: float = 0.0      # Rating set 2 [default: 0.0]
rate3: float = 0.0      # Rating set 3 [default: 0.0]
rate4: float = 0.0      # Rating set 4 [default: 0.0]
rate5: float = 0.0      # Rating set 5 [default: 0.0]
rate6: float = 0.0      # Rating set 6 [default: 0.0]
rate7: float = 0.0      # Rating set 7 [default: 0.0]
rate8: float = 0.0      # Rating set 8 [default: 0.0]
rate9: float = 0.0      # Rating set 9 [default: 0.0]
rate10: float = 0.0     # Rating set 10 [default: 0.0]
rate11: float = 0.0     # Rating set 11 [default: 0.0]
rate12: float = 0.0     # Rating set 12 [default: 0.0]

ierr = psspy.three_wnd_winding_data_5(
    i_bus,
    j_bus,
    k_bus,
    ckt,
    warg,
    [
        ntp,
        tab,
        cont,
        node,
        sicod,
        cod,
    ],
    [
        windv,
        nomv,
        ang,
        rma,
        rmi,
        vma,
        vmi,
        cr,
        cx,
        cnxa,
    ],
    [
        rate1,
        rate2,
        rate3,
        rate4,
        rate5,
        rate6,
        rate7,
        rate8,
        rate9,
        rate10,
        rate11,
        rate12,
    ],
)
```

#### Three-Winding Impedance Data

Batch syntax: `BAT_THREE_WND_IMPED_DATA_4 IBUS JBUS KBUS CKT INTGAR(1)..INTGAR(13) REALAR(1)..REALAR(17) NAMEAR VGRPAR`

Python syntax: `ierr, realaro = three_wnd_imped_data_4(ibus, jbus, kbus, ckt, intgar, realari, namear, vgrpar)`

```python
# Transformer identifiers
i_bus: int = 1          # Bus number of one transformer bus (no default)
j_bus: int = 2          # Bus number of another transformer bus (no default)
k_bus: int = 3          # Bus number of the third transformer bus (no default)
ckt: str = "1"          # Transformer circuit identifier [default: "1"]

# Ownership
o_1: int = 1            # First owner number [default: owner of i_bus]
o_2: int = 0            # Second owner number [default: 0]
o_3: int = 0            # Third owner number [default: 0]
o_4: int = 0            # Fourth owner number [default: 0]

# Transformer data I/O codes
cw: int = 1             # Winding data I/O code [default: 1]
cz: int = 1             # Impedance data I/O code [default: 1]
cm: int = 1             # Magnetizing admittance data I/O code [default: 1]

# Transformer status and bus assignments
stat: int = 1           # Branch status [default: 1]
nmetbs: int = j_bus     # Non-metered end bus number [default: j_bus]
wn1_bus: int = i_bus    # Winding 1 side bus number [default: i_bus]
wn2_bus: int = j_bus    # Winding 2 side bus number [default: j_bus]
wn3_bus: int = k_bus    # Winding 3 side bus number [default: k_bus]

# Impedance adjustment
zcod: int = 0           # 0 = winding impedances, 1 = bus-to-bus impedances [default: 0]

# Bus 1-to-2 impedance
r_1_2: float = 0.0      # Nominal bus 1-to-2 transformer resistance [default: 0.0]
x_1_2: float = 0.0002   # Nominal bus 1-to-2 transformer reactance [default: 0.0002]

# Bus 2-to-3 impedance
r_2_3: float = 0.0      # Nominal bus 2-to-3 transformer resistance [default: 0.0]
x_2_3: float = 0.0002   # Nominal bus 2-to-3 transformer reactance [default: 0.0002]

# Bus 3-to-1 impedance
r_3_1: float = 0.0      # Nominal bus 3-to-1 transformer resistance [default: 0.0]
x_3_1: float = 0.0002   # Nominal bus 3-to-1 transformer reactance [default: 0.0002]

# Winding base MVA
sbs_1_2: float = 100.0  # Winding 1-to-2 base MVA [default: system SBASE]
sbs_2_3: float = 100.0  # Winding 2-to-3 base MVA [default: system SBASE]
sbs_3_1: float = 100.0  # Winding 3-to-1 base MVA [default: system SBASE]

# Magnetizing admittance data
mag1: float = 0.0       # Magnetizing conductance / no-load losses [default: 0.0]
mag2: float = 0.0       # Magnetizing susceptance / exciting current [default: 0.0]

# Ownership fractions
f1: float = 1.0         # First owner fraction [default: 1.0]
f2: float = 0.0         # Second owner fraction [default: 0.0]
f3: float = 0.0         # Third owner fraction [default: 0.0]
f4: float = 0.0         # Fourth owner fraction [default: 0.0]

# Star bus voltage
vmstar: float = 1.0     # Star bus voltage magnitude in pu [default: 1.0]
tar: float = 0.0        # Star bus voltage angle in degrees [default: 0.0]

# Transformer identification
name: str = ""          # Transformer name, maximum 40 characters [default: blank]
vgrp: str = ""          # Vector group name, maximum 12 characters [default: blank]

ierr = psspy.three_wnd_imped_data_4(
    i_bus,
    j_bus,
    k_bus,
    ckt,
    [
        o_1,
        o_2,
        o_3,
        o_4,
        cw,
        cz,
        cm,
        stat,
        nmetbs,
        wn1_bus,
        wn2_bus,
        wn3_bus,
        zcod,
    ],
    [
        r_1_2,
        x_1_2,
        r_2_3,
        x_2_3,
        r_3_1,
        x_3_1,
        sbs_1_2,
        sbs_2_3,
        sbs_3_1,
        mag1,
        mag2,
        f1,
        f2,
        f3,
        f4,
        vmstar,
        tar,
    ],
    name,
    vgrp,
)
```

#### Fixed Shunt Data

Batch syntax: `BAT_SHUNT_DATA IBUS 'ID' INTGAR(1) REALAR(1) REALAR(2)`

Python syntax: `ierr = shunt_data(ibus, id, intgar, realar)`

```python
# Fixed shunt identifiers
i_bus: int = 1          # Bus number (no default)
shunt_id: str = "1"     # Shunt identifier [default: "1"]

# Integer data
status: int = 1         # Shunt status [default: 1]

# Shunt admittance data
gl: float = 0.0         # Fixed shunt admittance (conductance) [default: 0.0]
bl: float = 0.0         # Fixed shunt admittance (susceptance) [default: 0.0]

ierr = psspy.shunt_data(
    i_bus,
    shunt_id,
    [
        status,
    ],
    [
        gl,
        bl,
    ],
)
```

#### Switched Shunt Data

Batch syntax: `BAT_SWITCHED_SHUNT_DATA_5 IBUS 'ID' INTGAR(1)..INTGAR(21) REALAR(1)..REALAR(12) 'RMIDNT'`

Python syntax: `ierr = switched_shunt_data_5(ibus, id, intgar, realar, rmidnt)`

```python
# Switched shunt identifiers
i_bus: int = 1          # Bus number (no default)
shunt_id: str = "1"     # Switched shunt identifier [default: "1"]

# Number of steps per block
n1: int = 0             # Number of steps for block 1 [default: 0]
n2: int = 0             # Number of steps for block 2 [default: 0]
n3: int = 0             # Number of steps for block 3 [default: 0]
n4: int = 0             # Number of steps for block 4 [default: 0]
n5: int = 0             # Number of steps for block 5 [default: 0]
n6: int = 0             # Number of steps for block 6 [default: 0]
n7: int = 0             # Number of steps for block 7 [default: 0]
n8: int = 0             # Number of steps for block 8 [default: 0]

# Control data
modsw: int = 1          # Control mode [default: 1]
swrem: int = 0          # Regulated bus number [default: 0]
node: int = 0           # Regulated node number [default: 0]
stat: int = 1           # Switched shunt status [default: 1]
adjm: int = 0           # Adjustment method [default: 0]

# Block status
st1: int = 1            # Status of block 1 [default: 1]
st2: int = 1            # Status of block 2 [default: 1]
st3: int = 1            # Status of block 3 [default: 1]
st4: int = 1            # Status of block 4 [default: 1]
st5: int = 1            # Status of block 5 [default: 1]
st6: int = 1            # Status of block 6 [default: 1]
st7: int = 1            # Status of block 7 [default: 1]
st8: int = 1            # Status of block 8 [default: 1]

# Admittance increment per step
b1: float = 0.0         # Admittance increment per step for block 1 [default: 0.0]
b2: float = 0.0         # Admittance increment per step for block 2 [default: 0.0]
b3: float = 0.0         # Admittance increment per step for block 3 [default: 0.0]
b4: float = 0.0         # Admittance increment per step for block 4 [default: 0.0]
b5: float = 0.0         # Admittance increment per step for block 5 [default: 0.0]
b6: float = 0.0         # Admittance increment per step for block 6 [default: 0.0]
b7: float = 0.0         # Admittance increment per step for block 7 [default: 0.0]
b8: float = 0.0         # Admittance increment per step for block 8 [default: 0.0]

# Voltage control
vswhi: float = 1.0      # Desired voltage upper limit [default: 1.0]
vswlo: float = 1.0      # Desired voltage lower limit [default: 1.0]

# Initial admittance and reactive power contribution
binit: float = 0.0      # Present switched shunt admittance [default: 0.0]
rmpct: float = 100.0    # Percent of contributed reactive power [default: 100.0]

# Remote device identifier
rmidnt: str = ""        # VSC DC line name (MODSW=4) or FACTS device name (MODSW=6)
                        # [default: blank]

ierr = psspy.switched_shunt_data_5(
    i_bus,
    shunt_id,
    [
        n1,
        n2,
        n3,
        n4,
        n5,
        n6,
        n7,
        n8,
        modsw,
        swrem,
        node,
        stat,
        adjm,
        st1,
        st2,
        st3,
        st4,
        st5,
        st6,
        st7,
        st8,
    ],
    [
        b1,
        b2,
        b3,
        b4,
        b5,
        b6,
        b7,
        b8,
        vswhi,
        vswlo,
        binit,
        rmpct,
    ],
    rmidnt,
)
```

