# Tier And Operations Design

TripWeave assigns every user to one configurable tier. Tiers define trip, photo,
and monthly upload-byte limits; null trip or photo limits mean unlimited. The
initial tiers are Basic (5 trips, 100 photos, 2 GB/month), Plus (10, 200, 10
GB/month), and Unlimited (unlimited trips/photos, 50 GB/month).

Operators manage tiers and assignments. Per-user numerical overrides are not
part of the product model. The operations dashboard reports daily registrations,
active users, trips, photos, quota pressure, and distribution percentiles.
