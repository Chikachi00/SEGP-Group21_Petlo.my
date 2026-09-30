# Local Data Directory

## `data/raw/`

Use this directory for local source videos used in authorised experiments.

Raw project videos should normally stay local. Large videos should not be committed. Client-private videos must not be committed to the public repository.

## `data/frames/`

Use this directory for locally extracted frames and temporary inspection samples.

Extracted frame datasets should not be committed unless their source, permission status, size, and purpose have been specifically approved. The current ignore rules keep generated frames out of version control while retaining the empty directory placeholder.

## Future Labelled Data

If the future labelled dataset becomes too large for ordinary source control, the team should select suitable controlled data storage and record dataset versions separately from the application code. Access rules and retention decisions must be agreed before storing client-private material.

