# Todo list

## 1.0

### chore

- readme (more configuration examples)

### feat

- more info messages
  - downloaded messages that are skipped on filter conditions move progress
  - gentler recovery/more informative error handling
    - failing to login doesn't crash
    - failing to parse config doesn't crash
    - interrupt doesn't crash
    - add robust generic exception handler on top
    - remove empty header on error (so that it doesn't try to be read)
    - report on channel's downloading way of termination
      - no more messages
      - interruption
      - condition hit
      - session limit hit
      - connection timeout
      - skipped due to refusing to delete archive
- consider (lack of) support for custom statuses
