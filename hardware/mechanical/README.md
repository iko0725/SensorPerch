# Mechanical design

SolidWorks 2024 source of every part. References between files are relative to this folder, so keep its structure as it is.

| Open this | What it is |
|---|---|
| `Assemb - dlc.SLDASM` | The sensor module |
| `Charging Base/Single Camera Base_v2.SLDPRT` | Storage mount: the charging dock |
| `Attachment Ring/Attachment Ring Assemb.SLDASM` | Deployment mount: the attachment ring |

| Folder | What it holds |
|---|---|
| `Gimbal Assemb/` | The two-servo gimbal that carries the camera |
| `Battery Pack/` | The battery housing, lid and stoppers, and the battery PCB model |
| `Attachment Ring/` | The deployment mount, with its TPU liner and inserts |
| `Charging Base/` | The storage mount |
| `Pi4B/`, `Realsense/`, `MG90S/`, `303010 blower/`, `Electronics/` | Models of the purchased parts: Raspberry Pi 4B, RealSense D435i, MG90S servo, blower fan, switch, pogo connector and battery cell |
| `Hardware Library/` | Screws and nuts; file names carry McMaster-Carr part numbers |

Parts and quantities are in the [bill of materials](../../docs/bom.md).
