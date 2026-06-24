# AWS resources for reef-sfm-mote-keys

Final as-built inventory — recorded 2026-06-23 before decommission.
IDs are not secret but are no longer active after teardown.

## Instance

| Field | Value |
|-------|-------|
| instance_id | `i-06fe7879a0e713c2f` |
| instance_type | g6.4xlarge (NVIDIA L4) |
| region / AZ | us-east-1 / us-east-1c |
| key_pair | `reef-sfm-mote-keys-keypair` |
| state at inventory | running |

## Volumes

| Device | Volume ID | Size | DeleteOnTermination |
|--------|-----------|------|---------------------|
| /dev/sda1 (boot) | `vol-04511bde5db3641a8` | 200 GB | **true** — auto-deletes on terminate |
| /dev/sdf (data) | `vol-08bcf0ab11df2c9ed` | 1000 GB | **false** — must delete explicitly |

## Elastic IP

| Field | Value |
|-------|-------|
| public_ip | `52.5.136.119` |
| allocation_id | `eipalloc-0cfbcadb93a516508` |
| association_id | `eipassoc-0d01ba51e7c8654f3` |

## Secondary ENI (license fingerprint anchor)

| Field | Value |
|-------|-------|
| eni_id | `eni-0f576095ae0c469ae` |
| mac | `0a:ff:fc:67:89:8f` |
| description | Stable MAC for Metashape Pro license fingerprint |

## Security Group

| Field | Value |
|-------|-------|
| sg_id | `sg-0f252e1df4b0fd9af` |
| name | `reef-sfm-mote-keys-sg` |

## Snapshots (PRESERVED — do not delete)

| Snapshot | Volume | Role | State |
|----------|--------|------|-------|
| `snap-044e99b2343ea7a7c` | vol-04511bde5db3641a8 (boot) | boot-final as-built | completed 100% |
| `snap-01b844ca1259652fb` | vol-08bcf0ab11df2c9ed (data) | data-final as-built | completed 100% |
| `snap-01d7a140ed04a151e` | vol-08bcf0ab11df2c9ed (data) | data post-ortho export | completed 100% |
| `snap-034d45019a4e39c43` | vol-08bcf0ab11df2c9ed (data) | edr_t1_postproducts | completed |
| `snap-0b10abc94d12b78e1` | vol-08bcf0ab11df2c9ed (data) | edr_r2_postdense_filter_pre_aoi_dsm | completed |

## AMI (recorded after creation — see decommission log)

| Field | Value |
|-------|-------|
| ami_id | (recorded in decommission step 2) |
| name | reef-sfm-as-built-2026-06-23 |
| note | Convenience insurance only; teardown safety rests on snapshots + Mac-verified sha256 |

## Launch template

| Field | Value |
|-------|-------|
| launch_template_id | `lt-0673a3230668b47f6` |
| version | 3 |
