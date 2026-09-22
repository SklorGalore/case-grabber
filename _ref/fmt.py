import psspy

ierr = psspy.branch_data_3(
    i_bus: int = 			1,# Bus number of 'from' bus
    j_bus: int = 			2,# Bus number of 'to' bus
    ckt: str = 				"1",# Circuit identifier [1]
    [
  	st: int = 				,# Branch status. 1 or 0. [1]
    met_bus: int = 		,# metered end bus number [i_bus]
    o_1: int = 				,# id number of owner 1 [owner of i_bus]
    o_2: int = 				,# id number of owner 2 [0]
    o_3: int = 				,# id number of owner 3 [0]
    o_4: int = 				,# id number of owner 4 [0]
    ],
    [
      r: float = 				,# branch resistance [0]
      x: float = 				,# branch reactance [THRSHZ or .0001 if THRSHZ=0]
      b: float = 				,# TOTAL line charging [0]
      g_i: float = 			,# real line shunt at i_bus [0]
      b_i: float = 			,# imaginary line shunt at i_bus [0]
      g_j: float = 			,# real line shunt at j_bus [0]
      b_j: float = 			,# imaginary line shunt at j_bus [0]
      length: float = 	,# length of the line (typically in miles) [0]
      f1: float = 			,# fractional ownership of owner 1 [1]
      f2: float = 			,# fractional ownership of owner 2 [0]
      f3: float = 			,# fractional ownership of owner 3 [0]
      f4: float = 			,# fractional ownership of owner 4 [0]
    ],
  	[
      rate1: float = 		,# rating set 1 [0]
      rate2: float = 		,# rating set 2 [0]
      rate3: float = 		,# rating set 3 [0]
      rate4: float = 		,# rating set 4 [0]
      rate5: float = 		,# rating set 5 [0]
      rate6: float = 		,# rating set 6 [0]
      rate7: float = 		,# rating set 7 [0]
      rate8: float = 		,# rating set 8 [0]
      rate9: float = 		,# rating set 9 [0]
      rate10: float = 	,# rating set 10 [0]
      rate11: float = 	,# rating set 11 [0]
      rate12: float = 	,# rating set 12 [0]
    ]
)
