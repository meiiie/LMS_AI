"""
Import COLREGs data to Neo4j.
Focus on Rules 5-19 (Steering and Sailing Rules).

Usage:
    python scripts/import_colregs.py
"""
import os
import sys
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from neo4j import GraphDatabase
from dotenv import load_dotenv
import uuid

# Load environment variables
load_dotenv()

# Get Neo4j credentials from environment
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME", os.getenv("NEO4J_USER", "neo4j"))
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "neo4j_secret")

# COLREGs Rules 5-19 - Steering and Sailing Rules
COLREGS_DATA = [
    {
        "id": f"colregs_rule_5_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 5 - Look-out",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """Every vessel shall at all times maintain a proper look-out by sight and hearing as well as by all available means appropriate in the prevailing circumstances and conditions so as to make a full appraisal of the situation and of the risk of collision.

Key points:
1. Look-out must be maintained at ALL times
2. Use both sight AND hearing
3. Use all available means (radar, AIS, etc.)
4. Purpose: Full appraisal of situation and collision risk

Vietnamese: Mọi tàu phải luôn duy trì cảnh giới đúng đắn bằng mắt và tai cũng như bằng mọi phương tiện thích hợp để đánh giá đầy đủ tình huống và nguy cơ va chạm."""
    },
    {
        "id": f"colregs_rule_6_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 6 - Safe Speed",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """Every vessel shall at all times proceed at a safe speed so that she can take proper and effective action to avoid collision and be stopped within a distance appropriate to the prevailing circumstances and conditions.

Factors to consider:
1. Visibility conditions
2. Traffic density
3. Maneuverability of the vessel
4. Background light at night
5. Wind, sea and current conditions
6. Proximity of navigational hazards
7. Draft in relation to available depth

Vietnamese: Mọi tàu phải luôn chạy với tốc độ an toàn để có thể thực hiện hành động thích hợp và hiệu quả tránh va chạm."""
    },
    {
        "id": f"colregs_rule_7_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 7 - Risk of Collision",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """Every vessel shall use all available means appropriate to the prevailing circumstances and conditions to determine if risk of collision exists. If there is any doubt such risk shall be deemed to exist.

Key methods:
1. Radar plotting or equivalent systematic observation
2. Compass bearings - if bearing does not appreciably change, collision risk exists
3. Risk may exist even when bearing is changing (large vessels, towing, close range)

Vietnamese: Mọi tàu phải sử dụng mọi phương tiện thích hợp để xác định nguy cơ va chạm. Nếu có nghi ngờ, phải coi như nguy cơ tồn tại."""
    },
    {
        "id": f"colregs_rule_8_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 8 - Action to Avoid Collision",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """Any action to avoid collision shall be taken in accordance with the Rules of this Part and shall, if the circumstances of the case admit, be positive, made in ample time and with due regard to the observance of good seamanship.

Key principles:
1. Action must be POSITIVE (large enough to be readily apparent)
2. Action must be taken in AMPLE TIME
3. Alteration of course alone may be most effective if made in good time
4. Action shall result in passing at a safe distance
5. If necessary, vessel shall slacken speed, stop, or reverse

Vietnamese: Mọi hành động tránh va phải tích cực, kịp thời và đủ lớn để tàu khác nhận biết được."""
    },
    {
        "id": f"colregs_rule_9_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 9 - Narrow Channels",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """A vessel proceeding along the course of a narrow channel or fairway shall keep as near to the outer limit of the channel or fairway which lies on her starboard side as is safe and practicable.

Key rules:
1. Keep to starboard side of channel
2. Vessels less than 20m or sailing vessels shall not impede larger vessels
3. Vessels engaged in fishing shall not impede passage
4. No crossing if it impedes vessels that can only navigate within channel
5. Overtaking in narrow channel requires agreement (sound signals)

Vietnamese: Tàu đi trong luồng hẹp phải giữ càng gần mép phải của luồng càng tốt."""
    },
    {
        "id": f"colregs_rule_10_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 10 - Traffic Separation Schemes",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """This Rule applies to traffic separation schemes adopted by the Organization (IMO).

Key requirements:
1. Use appropriate traffic lane in general direction of traffic flow
2. Keep clear of separation line or zone
3. Join/leave traffic lane at termination or at small angle
4. Avoid crossing traffic lanes; if necessary, cross at right angles
5. Vessels not using TSS shall avoid it by wide margin
6. Vessels engaged in fishing shall not impede passage

Vietnamese: Tàu phải sử dụng làn giao thông đúng hướng và tránh cắt ngang làn giao thông."""
    },
    {
        "id": f"colregs_rule_12_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 12 - Sailing Vessels",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """When two sailing vessels are approaching one another, so as to involve risk of collision, one of them shall keep out of the way of the other as follows:

1. Wind on different sides: vessel with wind on PORT side keeps out of way
2. Wind on same side: vessel which is to WINDWARD keeps out of way
3. Vessel on port tack seeing vessel to windward cannot determine wind side: shall keep out of way

Vietnamese: Khi hai tàu buồm gặp nhau có nguy cơ va chạm:
- Gió khác mạn: tàu có gió mạn trái nhường đường
- Gió cùng mạn: tàu ở phía trên gió nhường đường"""
    },
    {
        "id": f"colregs_rule_13_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 13 - Overtaking",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """Any vessel overtaking any other shall keep out of the way of the vessel being overtaken.

Key points:
1. Overtaking vessel: coming up from direction more than 22.5° abaft the beam
2. At night: can only see sternlight, not sidelights
3. Overtaking vessel must keep clear until finally past and clear
4. Any doubt = assume overtaking
5. Subsequent alteration of bearing does not make overtaking vessel crossing vessel

Vietnamese: Tàu vượt phải nhường đường cho tàu bị vượt. Tàu vượt là tàu đến từ hướng hơn 22.5° sau chính ngang."""
    },
    {
        "id": f"colregs_rule_14_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 14 - Head-on Situation",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """When two power-driven vessels are meeting on reciprocal or nearly reciprocal courses so as to involve risk of collision each shall alter her course to STARBOARD so that each shall pass on the port side of the other.

Indicators of head-on:
1. At night: seeing both masthead lights in line or nearly in line AND/OR both sidelights
2. By day: corresponding aspect of the other vessel
3. Any doubt = assume head-on exists

Vietnamese: Khi hai tàu máy gặp nhau đối hướng, cả hai phải đổi hướng sang PHẢI để đi qua mạn trái của nhau."""
    },
    {
        "id": f"colregs_rule_15_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 15 - Crossing Situation",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """When two power-driven vessels are crossing so as to involve risk of collision, the vessel which has the other on her own STARBOARD side shall keep out of the way and shall, if the circumstances of the case admit, avoid crossing ahead of the other vessel.

Key points:
1. Give-way vessel: has other vessel on STARBOARD side
2. Stand-on vessel: has other vessel on PORT side
3. Give-way vessel should avoid crossing AHEAD of stand-on vessel
4. Give-way vessel should alter course to STARBOARD (pass astern)

Vietnamese: Khi hai tàu máy cắt hướng nhau, tàu nào thấy tàu kia ở mạn PHẢI của mình phải nhường đường."""
    },
    {
        "id": f"colregs_rule_16_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 16 - Action by Give-way Vessel",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """Every vessel which is directed to keep out of the way of another vessel shall, so far as possible, take early and substantial action to keep well clear.

Key requirements:
1. EARLY action - don't wait until last moment
2. SUBSTANTIAL action - large enough to be readily apparent
3. Keep WELL CLEAR - not just barely avoid collision

Vietnamese: Tàu nhường đường phải hành động SỚM và ĐỦ LỚN để tránh xa tàu được nhường."""
    },
    {
        "id": f"colregs_rule_17_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 17 - Action by Stand-on Vessel",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """(a) Where one of two vessels is to keep out of the way, the other shall keep her course and speed.

(b) The stand-on vessel may take action to avoid collision by her maneuver alone, as soon as it becomes apparent that the vessel required to keep out of the way is not taking appropriate action.

(c) When the stand-on vessel finds herself so close that collision cannot be avoided by the action of the give-way vessel alone, she shall take such action as will best aid to avoid collision.

(d) Stand-on vessel shall not alter course to PORT for a vessel on her own port side.

Vietnamese: Tàu được nhường phải giữ nguyên hướng và tốc độ. Nhưng khi thấy tàu nhường không hành động, có thể tự mình tránh va."""
    },
    {
        "id": f"colregs_rule_18_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 18 - Responsibilities Between Vessels",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """Except where Rules 9, 10 and 13 otherwise require:

Hierarchy of vessels (must give way to vessels below):
1. Power-driven vessel underway shall keep out of way of:
   - Vessel not under command
   - Vessel restricted in ability to maneuver
   - Vessel engaged in fishing
   - Sailing vessel

2. Sailing vessel underway shall keep out of way of:
   - Vessel not under command
   - Vessel restricted in ability to maneuver
   - Vessel engaged in fishing

3. Vessel engaged in fishing shall keep out of way of:
   - Vessel not under command
   - Vessel restricted in ability to maneuver

Vietnamese: Thứ tự ưu tiên: Tàu mất khả năng điều động > Tàu hạn chế khả năng điều động > Tàu đánh cá > Tàu buồm > Tàu máy"""
    },
    {
        "id": f"colregs_rule_19_{uuid.uuid4().hex[:8]}",
        "title": "COLREGs Rule 19 - Conduct in Restricted Visibility",
        "category": "COLREGs",
        "subcategory": "Steering and Sailing Rules",
        "source": "IMO COLREG 1972, as amended",
        "content": """This Rule applies to vessels not in sight of one another when navigating in or near an area of restricted visibility.

Key requirements:
1. Proceed at safe speed adapted to circumstances
2. Power-driven vessel shall have engines ready for immediate maneuver
3. Rules 11-18 do NOT apply (no stand-on/give-way)
4. Vessel detecting another by radar shall determine if close-quarters developing
5. Avoid alteration of course to PORT for vessel forward of beam (except overtaking)
6. Avoid alteration towards vessel abeam or abaft beam

Vietnamese: Trong tầm nhìn hạn chế, các quy tắc 11-18 không áp dụng. Tránh đổi hướng sang TRÁI cho tàu phía trước chính ngang."""
    },
]

def import_data():
    """Import COLREGs data to Neo4j using best practices from Neo4j documentation."""
    print(f"Connecting to Neo4j: {NEO4J_URI}")
    
    # Use 'with' statement as recommended by Neo4j docs (auto-closes driver)
    with GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USERNAME, NEO4J_PASSWORD)) as driver:
        # Verify connectivity first
        driver.verify_connectivity()
        print("✅ Neo4j connection verified")
        
        with driver.session() as session:
            # First, clear existing COLREGs data to avoid duplicates
            session.run("MATCH (k:Knowledge {category: 'COLREGs'}) DETACH DELETE k")
            print("Cleared existing COLREGs data")
            
            # Ensure Category exists
            session.run("""
                MERGE (c:Category {name: 'COLREGs'})
                SET c.description = 'International Regulations for Preventing Collisions at Sea'
            """)
            
            # Import each rule
            for rule in COLREGS_DATA:
                session.run("""
                    CREATE (k:Knowledge {
                        id: $id,
                        title: $title,
                        category: $category,
                        subcategory: $subcategory,
                        source: $source,
                        content: $content
                    })
                    WITH k
                    MATCH (c:Category {name: $category})
                    MERGE (k)-[:BELONGS_TO]->(c)
                """, **rule)
                print(f"Imported: {rule['title']}")
            
            # Count total
            result = session.run("MATCH (k:Knowledge) RETURN count(k) as count")
            print(f"\nTotal Knowledge nodes: {result.single()['count']}")
    
    print("✅ Neo4j driver closed automatically")

if __name__ == "__main__":
    import_data()
