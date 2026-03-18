#!../../bin/linux-x86_64/svcmgrApp

< /epics/common/localhost-netsetup.cmd

errlogInit(2000)
< envPaths

dbLoadDatabase("$(TOP)/dbd/svcmgrApp.dbd")
svcmgrApp_registerRecordDeviceDriver(pdbbase)

epicsEnvSet("PORT", "SVC")
epicsEnvSet("PREFIX", "DEV:SVC:")
epicsEnvSet("IP_PORT", "127.0.0.1:8000")
epicsEnvSet("STREAM_PROTOCOL_PATH", "$(TOP)/protocol")

drvAsynIPPortConfigure("$(PORT)", "$(IP_PORT)", 0)
asynOctetSetInputEos("$(PORT)", 0, "\n")
asynOctetSetOutputEos("$(PORT)", 0, "\n")

dbLoadRecords("$(TOP)/db/ManagedService.template", "P=$(PREFIX), R=MyService:, SVC=MyService")

iocInit()