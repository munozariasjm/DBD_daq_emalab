import pyvisa
rm = pyvisa.ResourceManager()
instr = rm.open_resource(rm.list_resources()[0])
print(instr.query("IDN?"))