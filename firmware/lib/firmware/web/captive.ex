defmodule Firmware.Web.Captive do
  @moduledoc """
  The box's captive portal: phones' "is this a captive network?" checks,
  answered so an iPhone opens the Observatory on join and then stays on the
  network.

  The box's access point answers every DNS name with itself (the `dnsd`
  records in config/target.exs), so a phone's check lands here:

    * iOS and macOS fetch `/hotspot-detect.html` and expect the word "Success".
    * Android fetches `/generate_204` and expects an empty 204.
    * Windows fetches `/connecttest.txt` or `/ncsi.txt`.

  An iPhone that finds no internet and no captive page it can get past marks
  the network broken and leaves it for one with internet. So the first check
  gets "yes, a portal": a small page with Continue, which iOS shows in its
  sheet. Continue records the phone (by the address the box's DHCP gave it),
  and from then on its checks get exactly the answer it wants, so it treats
  the network as good and stays. A reboot forgets, and asks again: one tap.
  """
  use Controller, :controller

  @home "http://192.168.24.1/"

  # Phones that have pressed Continue since this boot, and whether any phone
  # has asked at all (Firmware.Wireless keeps the access point for the boot
  # when one has, in the first minutes after power-on).
  def child_spec(_), do: %{id: __MODULE__, start: {Agent, :start_link, [fn -> %{accepted: MapSet.new(), seen: false} end, [name: __MODULE__]]}}

  @doc "Has any phone asked the captive portal anything since boot?"
  def seen? do
    Agent.get(__MODULE__, & &1.seen)
  catch
    :exit, _ -> false
  end

  defp accepted?(conn) do
    Agent.get_and_update(__MODULE__, fn s -> {MapSet.member?(s.accepted, conn.remote_ip), %{s | seen: true}} end)
  end

  defp accept(conn), do: Agent.update(__MODULE__, &%{&1 | accepted: MapSet.put(&1.accepted, conn.remote_ip), seen: true})

  # iOS, macOS
  def apple(conn, _params) do
    if accepted?(conn) do
      html(conn, "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>")
    else
      html(conn, portal_page())
    end
  end

  # Android, Windows, and anything that follows a redirect
  def redirect(conn, _params) do
    cond do
      accepted?(conn) and conn.request_path in ["/generate_204", "/gen_204"] -> send_resp(conn, 204, "")
      accepted?(conn) and conn.request_path == "/connecttest.txt" -> text(conn, "Microsoft Connect Test")
      accepted?(conn) and conn.request_path == "/ncsi.txt" -> text(conn, "Microsoft NCSI")
      true -> conn |> put_resp_header("location", "/portal") |> send_resp(302, "")
    end
  end

  def portal(conn, _params) do
    Agent.update(__MODULE__, &%{&1 | seen: true})
    html(conn, portal_page())
  end

  def continue(conn, _params) do
    accept(conn)
    conn |> put_resp_header("location", @home) |> send_resp(302, "")
  end

  defp portal_page do
    """
    <!doctype html>
    <html><head>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <meta name="color-scheme" content="dark">
    <title>Observatory</title>
    <style>
      body { background: #07080c; color: #c9ced8; font: 16px -apple-system, system-ui, sans-serif; margin: 0; padding: 32px 24px; }
      h1 { font-size: 20px; margin: 0 0 8px; color: #e8ebf1; }
      p { margin: 0 0 24px; line-height: 1.45; }
      a.go { display: block; text-align: center; background: #2457d6; color: #fff; text-decoration: none; padding: 14px; border-radius: 14px; font-weight: 600; }
    </style>
    </head><body>
    <h1>Observatory</h1>
    <p>Access point, no internet. Continue keeps this phone on it.</p>
    <p>#{@home}<br>http://#{Application.get_env(:firmware, :name, "telescope")}.local/</p>
    <a class="go" href="/portal/continue">Continue</a>
    </body></html>
    """
  end
end
