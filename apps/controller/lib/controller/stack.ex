defmodule Controller.Stack do
  @moduledoc """
  The control stack, live (#62): which control is driving the mount, at which
  law, and what each layer between the hand and the motors is doing about it.

  Controls report here with `note/2`: the Center touchpad and the pad's hat
  (law 1, through the eyepiece map), the pad's ball (law 0, straight to the
  motors), a GoTo (law 3, through the fitted geometry), a tracker (law 5).
  The Stack page listens on `topic/1` and draws the layers the input passes
  through. Nothing here moves anything.

  An event is a map: `law`, `source` (words a person reads), and whatever the
  layer can show: `rates` (axis → × sidereal), `view` ({x, y} in the eyepiece,
  y up), `speed`, `target` (`%{name, ra_deg, dec_deg}`), `model` (the fitted
  geometry: `axis_low`, `axis_west`, `off_pole`, `off_ra`, `off_dec`, `n`,
  `rms`), `error` ({ra, dec} arcminutes), `action`.
  """

  @doc "The PubSub topic for one mount's control events."
  def topic(id), do: "control:#{id}"

  @doc "Report what a control is doing to mount `id`."
  def note(id, %{law: law, source: _} = event) when law in 0..5 do
    msg = {:control, id, Map.put_new(event, :at, DateTime.utc_now())}
    Telescope.broadcast(topic(id), msg)
    Telescope.broadcast("control", msg)
  end

  @doc "The last report at each law for mount `id`, as this node heard them: a page opens on the real state."
  def last(id) do
    GenServer.call(__MODULE__.Memory, {:last, id}, 1_000)
  catch
    :exit, _ -> %{}
  end

  defmodule Memory do
    @moduledoc "Keeps the last control report per mount and law, from anywhere in the cluster."
    use GenServer

    def start_link(opts), do: GenServer.start_link(__MODULE__, opts, name: __MODULE__)

    @impl true
    def init(_) do
      Telescope.subscribe("control")
      {:ok, %{}}
    end

    @impl true
    def handle_call({:last, id}, _from, s), do: {:reply, Map.get(s, id, %{}), s}

    @impl true
    def handle_info({:control, id, %{law: law} = e}, s), do: {:noreply, Map.update(s, id, %{law => e}, &Map.put(&1, law, e))}
    def handle_info(_, s), do: {:noreply, s}
  end

  @doc "The layers an input at `law` passes through, top to bottom."
  def path(0), do: [0]
  def path(1), do: [1, 0]
  def path(2), do: [2, 1, 0]
  def path(3), do: [3, 4, 0]
  def path(4), do: [4, 3, 0]
  def path(5), do: [5, 3, 4, 0]
  def path(_), do: []

  @doc "The layers of a mount kind, top to bottom, as `{law, name, what it does}`."
  def layers(:gem) do
    [
      {5, "Tracking the target", "keeps what you centered in the middle, whatever the mount's errors"},
      {4, "Small sky corrections", "the target's own quirks, and the mount's mechanics"},
      {3, "Your mount's alignment", "how this mount is really sitting, measured from the sky"},
      {2, "If the mount were perfect", "the simple way: assume level, polar-aligned and home set upright"},
      {1, "Eyepiece directions", "which motor moves your view up, down, left or right"},
      {0, "Motors", "the two axes, as the mount reports them"}
    ]
  end

  # the NexStar 8SE (#30): the alignment fits the tilt of the base, not a polar axis
  def layers(:altaz) do
    [
      {5, "Tracking the target", "keeps what you centered in the middle"},
      {4, "Small sky corrections", "the target's own quirks, and the mount's mechanics"},
      {3, "Your mount's alignment", "how the base is tilted, measured from two stars"},
      {2, "If the mount were perfect", "the simple way: assume a level base"},
      {1, "Eyepiece directions", "which motor moves your view up, down, left or right"},
      {0, "Motors", "altitude and azimuth, as the mount reports them"}
    ]
  end
end
