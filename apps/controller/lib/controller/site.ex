defmodule Controller.Site do
  @moduledoc """
  Words for where the observatory is, shared by the pages that ask for it
  (Site, Sky). The location itself is `Controller.Sky.Pointing.site/0`.
  """

  @doc """
  One line for a location the browser would not give. `"insecure"` is the
  Geo hook saying the page is plain http: browsers share location only with
  https pages, and a box serves http, so there the answer is always to type
  it.
  """
  def location_error("insecure"),
    do: "This page is http, and browsers only share location with https pages. Type the latitude and longitude instead: the iPhone Compass app shows them."

  def location_error(reason), do: "Location: #{reason}"
end
