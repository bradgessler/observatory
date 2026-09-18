defmodule Mount.Transport do
  @moduledoc """
  Something that carries one protocol frame to the motor controller and brings
  the reply back. Real hardware uses `Mount.Transport.Serial`; tests and
  hardware-less dev use `Mount.Transport.Sim`, which speaks the same wire
  protocol so the driver code above it is identical.
  """

  @type state :: term

  @callback open(keyword) :: {:ok, state} | {:error, term}
  @callback exchange(state, binary) :: {:ok, binary, state} | {:error, term, state}
  @callback close(state) :: :ok
end
