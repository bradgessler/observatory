defmodule Camera.Transport do
  @moduledoc """
  Moves bytes between `Camera.Ptp` and a camera: one USB transfer per call.
  Real cameras use `Camera.Transport.Usb` (the `usbport` helper); tests and
  hardware-less machines use `Camera.Transport.Sim`, which answers the same
  protocol with a recorded a6000's bytes, so the code above is identical.
  """

  @type state :: term

  @doc "Open the camera's still-image interface."
  @callback open(keyword) :: {:ok, state} | {:error, term}

  @doc "One bulk-out transfer (the transport adds the zero-length packet a full last packet needs)."
  @callback write(state, binary, timeout) :: {:ok, state} | {:error, term, state}

  @doc "One bulk-in transfer, at most `max` bytes."
  @callback read(state, max :: pos_integer, timeout) ::
              {:ok, binary, state} | {:error, term, state}

  @doc "One event from the interrupt pipe, if it comes within `timeout`."
  @callback event(state, timeout) :: {:ok, binary, state} | {:none, state} | {:error, term, state}

  @callback close(state) :: :ok
end
