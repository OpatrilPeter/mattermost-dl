# Todo list

## 1.0

### chore

- readme (detailed description of usage, notion of script samples)
- make scripts rugged
- add versioning to config

### feat
- safety mode - do not trim archive without confirmation (redownload or interactive ask) - if trim is needed channel download fails
- more info messages
  - downloaded messages that are skipped on filter conditions move progress
  - gentler recovery/more informative error handling
    - interrupt doesn't cause error
    - remove empty header on error (so that it doesn't try to be read)
    - report on channel's downloading way of termination
      - no more messages
      - interruption
      - condition hit
      - session limit hit
      - connection timeout
      - skipped due to refusing to delete archive
  - json schema validator
